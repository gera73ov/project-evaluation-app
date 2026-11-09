"""CORE-011 · жизненный цикл проекта (SPEC 4.2, FR-PRJ-05, BR-PRJ-01, BR-PRJ-03, BR-PRJ-04;
15.2 ``POST /projects/{id}/status``).

Переходы — только по стрелкам диаграммы 4.2 (permissions.yaml D-04, сверяется тестом); прочие —
409 ``INVALID_TRANSITION``. Отмена «Оценка → Архив» требует причину 10–500 символов. Каждый
переход — запись журнала проекта, аудит ``project.status.changed`` и событие
``project.updated`` с ``changes.status``.

Предупреждения (``warnings``) отдаются в ответе для показа после перехода и считаются по
состоянию проекта до перехода (таблица FR-PRJ-05): дисциплины без эксперта при запуске оценки,
ветки «черновик» / «не начато» при переходе к сведению и при завершении, открытые вопросы
заказчику и отсутствие снимка при завершении.

Толкования (agents/journal/DEC-20261109-core-team-lifecycle.md):

* «Восстановить» (Архив → Завершена) ставит ``completed_at`` заново — иначе ночная
  автоархивация (BR-PRJ-03) вернула бы проект в архив в ту же ночь; причина отмены снимается.
* Открытый вопрос заказчику — в состояниях «новый», «отправлен», «отвечен» (не «решён» и не
  «снят», 4.4).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import (
    BranchStatusValue,
    CustomerQuestionStatus,
    ProjectRole,
    ProjectStatus,
)
from estimator.db.models.dictionaries import Phase
from estimator.db.models.discussions import Thread
from estimator.db.models.files import Snapshot
from estimator.db.models.projects import BranchStatus, Project, ProjectMember, ProjectPhase
from estimator.notifications import inapp
from estimator.security import audit
from estimator.services.common import emit, user_ref
from estimator.services.projects import journal
from estimator.services.tree.load import project_disciplines

P = ProjectStatus

#: Диаграмма 4.2 (permissions.yaml, derived_status_gates D-04)
TRANSITIONS: Mapping[ProjectStatus, frozenset[ProjectStatus]] = {
    P.PREPARATION: frozenset({P.ESTIMATION}),
    P.ESTIMATION: frozenset({P.CONSOLIDATION, P.ARCHIVED}),
    P.CONSOLIDATION: frozenset({P.ESTIMATION, P.COMPLETED}),
    P.COMPLETED: frozenset({P.ESTIMATION, P.ARCHIVED}),
    P.ARCHIVED: frozenset({P.COMPLETED}),
}

REASON_MIN, REASON_MAX = 10, 500
_NOT_DONE = (BranchStatusValue.NOT_STARTED, BranchStatusValue.DRAFT)
_OPEN_CQ = (
    CustomerQuestionStatus.NEW,
    CustomerQuestionStatus.SENT,
    CustomerQuestionStatus.ANSWERED,
)
#: При запуске оценки «Вас назначили» получают эксперты, ревьюеры и пресейл (BR-PRJ-01)
LAUNCH_ROLES = (ProjectRole.EXPERT, ProjectRole.PRESALE)


def is_cancel(frm: ProjectStatus, to: ProjectStatus) -> bool:
    return frm is P.ESTIMATION and to is P.ARCHIVED


async def branches_not_done(db: AsyncSession, project_id: uuid.UUID) -> int:
    """Ветки «не начато» и «черновик» во включённых фазах работ."""
    stmt = (
        select(func.count())
        .select_from(BranchStatus)
        .join(
            ProjectPhase,
            (ProjectPhase.project_id == BranchStatus.project_id)
            & (ProjectPhase.phase_id == BranchStatus.phase_id),
        )
        .join(Phase, Phase.id == BranchStatus.phase_id)
        .where(
            BranchStatus.project_id == project_id,
            ProjectPhase.is_enabled,
            Phase.is_cross_cutting.is_(False),
            BranchStatus.status.in_(_NOT_DONE),
        )
    )
    return int(await db.scalar(stmt) or 0)


async def all_branches_ready(db: AsyncSession, project_id: uuid.UUID) -> bool:
    """Признак баннера «Все ветки готовы. Перейти к сведению?» (BR-PRJ-01)."""
    has_branches = await db.scalar(
        select(func.count()).select_from(BranchStatus).where(BranchStatus.project_id == project_id)
    )
    return bool(has_branches) and await branches_not_done(db, project_id) == 0


async def open_customer_questions(db: AsyncSession, project_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        Thread.project_id == project_id,
        Thread.is_customer,
        Thread.customer_status.in_(_OPEN_CQ),
    )
    return int(await db.scalar(stmt) or 0)


async def has_snapshot(db: AsyncSession, project_id: uuid.UUID) -> bool:
    stmt = select(func.count()).where(
        Snapshot.project_id == project_id, Snapshot.is_invalid.is_(False)
    )
    return bool(await db.scalar(stmt))


async def warnings_for(
    db: AsyncSession, project_id: uuid.UUID, frm: ProjectStatus, to: ProjectStatus
) -> list[dict[str, Any]]:
    """Предупреждения перехода (FR-PRJ-05, столбец «Подтверждение»), только ненулевые."""
    found: dict[str, int] = {}
    if frm is P.PREPARATION and to is P.ESTIMATION:
        disciplines = await project_disciplines(db, project_id)
        found["disciplines_without_expert"] = sum(1 for d in disciplines if not d.has_expert)
    if to in (P.CONSOLIDATION, P.COMPLETED) and frm is not P.ARCHIVED:
        found["branches_not_done"] = await branches_not_done(db, project_id)
    if frm is P.CONSOLIDATION and to is P.COMPLETED:
        found["open_customer_questions"] = await open_customer_questions(db, project_id)
        found["no_snapshot"] = 0 if await has_snapshot(db, project_id) else 1
    return [{"code": code, "count": count} for code, count in found.items() if count]


def _reason_error(message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": "/reason", "code": "required", "message": message}],
    )


async def change_status(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    to: ProjectStatus,
    reason: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Перевести проект в статус ``to``; ``(project_version, warnings)``."""
    frm = ProjectStatus(project.status)
    if to not in TRANSITIONS[frm]:
        raise ApiError("INVALID_TRANSITION", **{"from": frm.value, "to": to.value})
    cancel = is_cancel(frm, to)
    text = (reason or "").strip()
    if cancel and not REASON_MIN <= len(text) <= REASON_MAX:
        raise _reason_error("Укажите причину отмены проекта: от 10 до 500 символов")

    warnings = await warnings_for(db, project.id, frm, to)
    now = dt.datetime.now(dt.UTC)
    project.status = to
    project.updated_by = principal.user_id
    if to is P.COMPLETED:
        project.completed_at = now
        project.archived_at = None
        project.cancel_reason = None
    elif to is P.ARCHIVED:
        project.archived_at = now
        project.cancel_reason = text if cancel else None
    elif to is P.ESTIMATION:
        project.archived_at = None
    await db.flush()

    changes: dict[str, tuple[Any, Any]] = {"status": (frm.value, to.value)}
    if cancel:
        changes["cancel_reason"] = (None, text)
    journal.record(db, project.id, principal.user_id, "project.status", changes)
    await audit.write(
        db,
        "project.status.changed",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        details={
            "from": frm.value,
            "to": to.value,
            "automatic": False,
            "cancel_reason": text if cancel else None,
        },
    )
    version = await emit(
        db,
        project.id,
        "project.updated",
        {
            "changes": {"status": to.value},
            "author": user_ref(principal.user_id, principal.full_name),
        },
    )
    project.version = version
    if frm is P.PREPARATION and to is P.ESTIMATION:
        await notify_launch(db, principal, project.id)
    return version, warnings


async def notify_launch(db: AsyncSession, principal: Principal, project_id: uuid.UUID) -> None:
    """«Вас назначили в проект» всем, кто назначен в «Подготовке» и ещё не уведомлён (BR-PRJ-01).

    Письмо (NTF-006) уйдёт по тем же строкам ``project_members.notified_at``.
    """
    rows = list(
        (
            await db.scalars(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role.in_(LAUNCH_ROLES),
                    ProjectMember.notified_at.is_(None),
                )
            )
        ).all()
    )
    await notify_assigned(db, principal, project_id, rows)


async def notify_assigned(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    rows: list[ProjectMember],
) -> None:
    """Уведомление ``assigned_to_project`` по строкам команды: одно на пользователя."""
    by_user: dict[uuid.UUID, list[ProjectMember]] = {}
    for row in rows:
        by_user.setdefault(row.user_id, []).append(row)
    now = dt.datetime.now(dt.UTC)
    for user_id, mine in sorted(by_user.items()):
        payload = {
            "project_id": str(project_id),
            "actor_id": str(principal.user_id),
            "roles": sorted({str(r.role) for r in mine}),
            "discipline_ids": sorted({str(r.discipline_id) for r in mine if r.discipline_id}),
        }
        await inapp.notify(
            db,
            "assigned_to_project",
            [user_id],
            project_id=project_id,
            payload=payload,
            actor_id=principal.user_id,
        )
        for row in mine:
            row.notified_at = now
    await db.flush()
