"""CORE-010 · создание проекта и основные настройки (SPEC FR-PRJ-01, FR-PRJ-05 «Создание»,
FR-HOME-03, 5.1, BR-CALC-05, BR-MONEY-05/06, BR-PRJ-06, C-31; 15.2 ``POST /projects``,
``GET/PATCH /projects/{id}``).

Толкования (записаны в описании PR):

* В проекте хранятся строки ``project_phases`` для всех активных фаз справочника: невыбранные —
  выключены, их можно включить в настройках. Узел-фаза создаётся для включённой фазы; узел
  выключенной фазы остаётся в дереве, а её ветки уходят в корзину (5.1).
* База УП по умолчанию — все фазы работ, кроме «Гарантийная поддержка» (по названию фазы
  справочника, BR-CALC-05); сквозная фаза «Управление проектом» в базу не входит.
* Создатель с системной ролью «Администратор» помечается ``added_by_admin_self`` (Q-25).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.policy import read_settings
from estimator.db.enums import (
    BranchStatusValue,
    DetailLevel,
    NodeKind,
    ProjectRole,
    ProjectStatus,
    QuoteFigure,
    SystemRole,
)
from estimator.db.models.dictionaries import Phase
from estimator.db.models.projects import (
    BranchStatus,
    Project,
    ProjectDiscipline,
    ProjectMember,
    ProjectPhase,
)
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.realtime.bus import publish
from estimator.security import audit
from estimator.services import money
from estimator.services.common import app_today, bump_version, log_change, user_ref
from estimator.services.projects import journal, totals
from estimator.services.tree.load import project_disciplines, project_phases
from estimator.services.tree.positions import key_between, keys_after

WARRANTY_PHASE = "Гарантийная поддержка"  # по умолчанию не в базе УП (BR-CALC-05)
PM_PERCENT_DEFAULT = Decimal(18)  # method.pm_percent_default (settings.schema.json)
PM_PERCENT_MAX = Decimal(50)
_HALF = Decimal("0.5")


@dataclass(frozen=True)
class NewProject:
    name: str
    customer: str
    phase_ids: Sequence[uuid.UUID]
    description: str = ""
    detail_level: DetailLevel = DetailLevel.MEDIUM
    deadline: dt.date | None = None


def _out_of_range(field: str, low: Any, high: Any, detail: str) -> ApiError:
    return ApiError("VALUE_OUT_OF_RANGE", detail=detail, field=field, min=str(low), max=str(high))


async def _check_deadline(db: AsyncSession, deadline: dt.date | None) -> None:
    if deadline is None:
        return
    today = await app_today(db)
    if deadline < today:
        raise ApiError(
            "VALUE_OUT_OF_RANGE",
            detail="Дедлайн не может быть раньше сегодняшнего дня",
            field="deadline",
            min=today.isoformat(),
        )


async def _pm_percent_default(db: AsyncSession) -> Decimal:
    raw = (await read_settings(db, "method.pm_percent_default")).get("method.pm_percent_default")
    if isinstance(raw, int | float | str):
        try:
            value = Decimal(str(raw))
        except ArithmeticError:  # pragma: no cover — значение проверено схемой настроек
            return PM_PERCENT_DEFAULT
        if 0 <= value <= PM_PERCENT_MAX and (value * 2) % 1 == 0:
            return value
    return PM_PERCENT_DEFAULT


def _validation(field: str, message: str, code: str = "invalid") -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": field, "code": code, "message": message}],
    )


async def create_project(db: AsyncSession, principal: Principal, data: NewProject) -> Project:
    """Проект в «Подготовке»: фазы, узлы фаз, деньги по умолчанию, создатель — модератор."""
    await _check_deadline(db, data.deadline)
    active = list(
        (
            await db.scalars(
                select(Phase).where(Phase.is_active).order_by(Phase.sort_order, Phase.name)
            )
        ).all()
    )
    known = {p.id for p in active}
    chosen = set(data.phase_ids)
    unknown = chosen - known
    if unknown:
        raise _validation("/phase_ids", "Фаза не найдена среди активных фаз справочника")
    cross = next((p for p in active if p.is_cross_cutting), None)
    if cross is not None:
        chosen.add(cross.id)  # «Управление проектом» включена всегда (5.1)
    if not chosen - ({cross.id} if cross else set()):
        raise _validation("/phase_ids", "Выберите хотя бы одну фазу работ", "too_short")

    project = Project(
        id=uuid7(),
        name=data.name.strip(),
        customer=data.customer.strip(),
        description=data.description,
        detail_level=data.detail_level,
        quote_figure=QuoteFigure.P80,
        pm_percent=await _pm_percent_default(db),
        deadline=data.deadline,
        status=ProjectStatus.PREPARATION,
        version=1,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(project)
    await db.flush()
    positions = iter(keys_after(None, len(active)))
    for phase in active:
        enabled = phase.id in chosen
        db.add(
            ProjectPhase(
                project_id=project.id,
                phase_id=phase.id,
                is_enabled=enabled,
                in_pm_base=not phase.is_cross_cutting and phase.name != WARRANTY_PHASE,
            )
        )
        position = next(positions)
        if enabled:
            db.add(_phase_node(project.id, phase, position, principal.user_id))
    admin_self = SystemRole.ADMIN in principal.roles
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=principal.user_id,
            role=ProjectRole.MODERATOR,
            added_by_admin_self=admin_self,
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
    )
    await money.create_defaults(db, project.id, principal.user_id)
    await db.flush()
    totals.schedule(db, project.id)  # кэш итогов для «Моих оценок» (CORE-026)
    journal.record(
        db,
        project.id,
        principal.user_id,
        "project.created",
        {
            "name": (None, project.name),
            "customer": (None, project.customer),
            "phases": (None, sorted(str(p) for p in chosen)),
        },
    )
    await audit.write(
        db,
        "project.created",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        details={"copied_from": None, "rates_copied": False},
    )
    await audit.write(
        db,
        "project.team.changed",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project_member",
        object_id=principal.user_id,
        project_id=project.id,
        details={
            "op": "added",
            "member_user_id": str(principal.user_id),
            "role": "moderator",
            "discipline_id": None,
            "is_reviewer": False,
            "added_by_admin_self": admin_self,
            "via": "team",
        },
    )
    return project


def _phase_node(
    project_id: uuid.UUID, phase: Phase, position: str, user_id: uuid.UUID | None
) -> Node:
    return Node(
        id=uuid7(),
        project_id=project_id,
        parent_id=None,
        kind=NodeKind.PHASE,
        phase_id=phase.id,
        title=phase.name,
        position=position,
        created_by=user_id,
        updated_by=user_id,
    )


def _timestamp(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


async def project_out(
    db: AsyncSession,
    project: Project,
    *,
    access: str,
    my_permissions: Sequence[str],
    support_expires_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """Тело ``Project`` (настройки без денег, 11.6)."""
    phases = await project_phases(db, project.id)
    disciplines = await project_disciplines(db, project.id)
    body: dict[str, Any] = {
        "id": str(project.id),
        "name": project.name,
        "customer": project.customer,
        "description": project.description,
        "status": str(project.status),
        "outcome": str(project.outcome),
        "detail_level": str(project.detail_level),
        "pm_percent": format_decimal(project.pm_percent),
        "pm_percent_reason": project.pm_percent_reason,
        "quote_figure": str(project.quote_figure),
        "duration_weeks": project.duration_weeks,
        "deadline": project.deadline.isoformat() if project.deadline else None,
        "version": project.version,
        "phases": [
            {
                "phase_id": str(p.phase_id),
                "name": p.name,
                "is_cross_cutting": p.is_cross_cutting,
                "is_enabled": p.is_enabled,
                "in_pm_base": p.in_pm_base,
            }
            for p in phases
        ],
        "disciplines": [
            {
                "discipline_id": str(d.discipline_id),
                "name": d.name,
                "profile_id": str(d.profile_id),
                "has_expert": d.has_expert,
            }
            for d in disciplines
        ],
        "completed_at": _timestamp(project.completed_at),
        "archived_at": _timestamp(project.archived_at),
        "cancel_reason": project.cancel_reason,
        "created_at": _timestamp(project.created_at),
        "access": access,
        "my_permissions": sorted(my_permissions),
    }
    if support_expires_at is not None:
        body["support_expires_at"] = _timestamp(support_expires_at)
    return body


# --- PATCH /projects/{id} ---------------------------------------------------------------------

#: Поля настроек и их ключ в событии project.updated (ws-events.schema.json)
SIMPLE_FIELDS = (
    "name",
    "customer",
    "description",
    "detail_level",
    "pm_percent",
    "pm_percent_reason",
    "quote_figure",
    "duration_weeks",
    "deadline",
)


@dataclass(frozen=True)
class PhaseChange:
    phase_id: uuid.UUID
    is_enabled: bool | None = None
    in_pm_base: bool | None = None


def _check_pm_percent(value: Decimal) -> Decimal:
    if not 0 <= value <= PM_PERCENT_MAX:
        raise _out_of_range("pm_percent", 0, 50, "Процент УП должен быть от 0 до 50")
    if (value * 2) % 1 != 0:
        raise _out_of_range("pm_percent", 0, 50, "Процент УП задаётся с шагом 0,5")
    return value


def _value(project: Project, field: str) -> Any:
    value = getattr(project, field)
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


async def patch_project(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    values: Mapping[str, Any],
    phases: Sequence[PhaseChange] | None,
    *,
    confirm: bool = False,
) -> int:
    """Изменить настройки; возвращает новую ``project_version`` (или прежнюю без изменений)."""
    changes: dict[str, tuple[Any, Any]] = {}
    for field in SIMPLE_FIELDS:
        if field not in values:
            continue
        new = values[field]
        if field in ("name", "customer") and isinstance(new, str):
            new = new.strip()
            minimum = 3 if field == "name" else 1
            if len(new) < minimum:
                raise _validation(f"/{field}", "Слишком короткое значение", "too_short")
        if field == "pm_percent":
            new = _check_pm_percent(new)
        if field == "deadline" and new != project.deadline:
            await _check_deadline(db, new)
        if new != getattr(project, field):
            old = _value(project, field)
            setattr(project, field, new)
            changes[field] = (old, _value(project, field))

    phase_events: dict[str, Any] = {}
    if phases:
        phase_events = await _apply_phases(db, principal, project, phases, confirm=confirm)
        if "phases" in phase_events:
            changes["phases"] = phase_events["phases"]
        if "pm_base_phase_ids" in phase_events:
            changes["pm_base_phase_ids"] = phase_events["pm_base_phase_ids"]

    if not changes:
        return project.version
    project.updated_by = principal.user_id
    await db.flush()
    version = await bump_version(db, project.id)
    project.version = version
    journal.record(db, project.id, principal.user_id, "project.settings", changes)
    event_changes = {k: new for k, (_old, new) in changes.items()}
    data = {
        "changes": journal.plain(event_changes),
        "author": user_ref(principal.user_id, principal.full_name),
    }
    message = publish(db, f"project:{project.id}", "project.updated", data, project_version=version)
    log_change(db, project.id, version, message)
    return version


async def _apply_phases(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    changes: Sequence[PhaseChange],
    *,
    confirm: bool,
) -> dict[str, Any]:
    rows = {
        r.phase_id: r
        for r in (
            await db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project.id))
        ).all()
    }
    dictionary = {
        p.id: p for p in (await db.scalars(select(Phase).where(Phase.id.in_(list(rows))))).all()
    }
    before_enabled = sorted(str(k) for k, r in rows.items() if r.is_enabled)
    before_base = sorted(str(k) for k, r in rows.items() if r.in_pm_base)
    turning_off: list[uuid.UUID] = []
    turning_on: list[uuid.UUID] = []
    for change in changes:
        row = rows.get(change.phase_id)
        if row is None:
            raise _validation("/phases", "Фаза не входит в проект")
        phase = dictionary[change.phase_id]
        if change.is_enabled is not None and change.is_enabled != row.is_enabled:
            if phase.is_cross_cutting:
                raise ApiError("CROSS_CUTTING_PHASE_LOCKED")
            if change.is_enabled and not phase.is_active:
                raise _validation("/phases", "Фаза выключена в справочнике")
            (turning_on if change.is_enabled else turning_off).append(change.phase_id)
        if change.in_pm_base is not None and change.in_pm_base != row.in_pm_base:
            if phase.is_cross_cutting and change.in_pm_base:
                raise _validation("/phases", "Фаза «Управление проектом» не входит в базу УП")
            row.in_pm_base = change.in_pm_base

    if turning_off:
        enabled_work = [
            k for k, r in rows.items() if r.is_enabled and not dictionary[k].is_cross_cutting
        ]
        if not set(enabled_work) - set(turning_off) and not turning_on:
            raise _validation("/phases", "В проекте должна остаться хотя бы одна фаза работ")
        affected = await _filled_branches(db, project.id, turning_off)
        if affected and not confirm:
            raise ApiError(
                "CONFIRMATION_REQUIRED",
                detail="Ветки выключаемых фаз уйдут в корзину",
                consequence="branches_to_trash",
                affected=affected,
            )
        await _trash_branches(db, principal, project.id, turning_off)
        for phase_id in turning_off:
            rows[phase_id].is_enabled = False
    for phase_id in turning_on:
        rows[phase_id].is_enabled = True
        await _ensure_phase_nodes(db, principal, project.id, dictionary[phase_id])

    out: dict[str, Any] = {}
    after_enabled = sorted(str(k) for k, r in rows.items() if r.is_enabled)
    after_base = sorted(str(k) for k, r in rows.items() if r.in_pm_base)
    if after_enabled != before_enabled:
        out["phases"] = (before_enabled, after_enabled)
    if after_base != before_base:
        out["pm_base_phase_ids"] = (before_base, after_base)
    return out


async def _filled_branches(
    db: AsyncSession, project_id: uuid.UUID, phase_ids: Sequence[uuid.UUID]
) -> int:
    """Число непустых веток (есть живые дети) в фазах ``phase_ids``."""
    child = Node.__table__.alias("child")
    stmt = (
        select(Node.id)
        .where(
            Node.project_id == project_id,
            Node.kind == NodeKind.DISCIPLINE,
            Node.deleted_at.is_(None),
            Node.phase_id.in_(list(phase_ids)),
        )
        .where(
            select(child.c.id)
            .where(child.c.parent_id == Node.id, child.c.deleted_at.is_(None))
            .exists()
        )
    )
    return len((await db.scalars(stmt)).all())


async def _trash_branches(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    phase_ids: Sequence[uuid.UUID],
) -> None:
    """Ветки выключаемых фаз со всеми детьми — в корзину одним пакетом (5.1, BR-TREE-03)."""
    batch = uuid7()
    now = dt.datetime.now(dt.UTC)
    await db.execute(
        update(Node)
        .where(
            Node.project_id == project_id,
            Node.phase_id.in_(list(phase_ids)),
            Node.kind != NodeKind.PHASE,
            Node.deleted_at.is_(None),
        )
        .values(deleted_at=now, deleted_batch_id=batch, deleted_by=principal.user_id)
        .execution_options(synchronize_session=False)
    )


async def _ensure_phase_nodes(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID, phase: Phase
) -> None:
    """Включённая фаза: узел-фаза и ветки дисциплин проекта, если их нет."""
    live = select(Node).where(
        Node.project_id == project_id, Node.phase_id == phase.id, Node.deleted_at.is_(None)
    )
    existing = list((await db.scalars(live)).all())
    phase_node = next((n for n in existing if n.kind is NodeKind.PHASE), None)
    if phase_node is None:
        roots = (
            await db.scalars(
                select(Node.position).where(
                    Node.project_id == project_id,
                    Node.parent_id.is_(None),
                    Node.deleted_at.is_(None),
                )
            )
        ).all()
        phase_node = _phase_node(
            project_id, phase, key_between(max(roots, default=None), None), principal.user_id
        )
        db.add(phase_node)
        await db.flush()
    if phase.is_cross_cutting:
        return
    have = {n.discipline_id for n in existing if n.kind is NodeKind.DISCIPLINE}
    disciplines = list(
        (
            await db.scalars(
                select(ProjectDiscipline.discipline_id).where(
                    ProjectDiscipline.project_id == project_id
                )
            )
        ).all()
    )
    names = {d.discipline_id: d.name for d in await project_disciplines(db, project_id)}
    last: str | None = None
    for discipline_id in sorted(disciplines, key=lambda d: names.get(d, "")):
        if discipline_id in have:
            continue
        last = key_between(last, None)
        db.add(
            Node(
                id=uuid7(),
                project_id=project_id,
                parent_id=phase_node.id,
                kind=NodeKind.DISCIPLINE,
                phase_id=phase.id,
                discipline_id=discipline_id,
                title=names.get(discipline_id, ""),
                position=last,
                created_by=principal.user_id,
                updated_by=principal.user_id,
            )
        )
        status = await db.get(BranchStatus, (project_id, phase.id, discipline_id))
        if status is not None:
            # прежние ветки ушли в корзину вместе с выключением фазы — новая ветка не начата
            status.status = BranchStatusValue.NOT_STARTED
            status.changed_by = principal.user_id
            status.changed_at = dt.datetime.now(dt.UTC)
        else:
            db.add(
                BranchStatus(
                    project_id=project_id,
                    phase_id=phase.id,
                    discipline_id=discipline_id,
                    status=BranchStatusValue.NOT_STARTED,
                )
            )
