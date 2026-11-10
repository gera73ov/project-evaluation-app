"""CORE-060 · снимки оценки (SPEC FR-SNAP-01, FR-SNAP-02, BR-PRJ-02, BR-ADM-02, FR-NOTE-01,
SEC-AUTHZ-04; 15.2 ``GET/POST /projects/{id}/snapshots``, ``POST /snapshots/{id}/invalidate``).

``payload`` (версия ``schema: 1``) самодостаточен: из него без БД заново считаются часы и
строится сравнение (CORE-061), поэтому переименование фазы, дисциплины, типа или метки в
справочнике снимок не меняет. В нём:

* ``project`` — процент и обоснование УП, уровень, «Цифра для КП», срок в неделях, дедлайн, статус;
* ``phases`` (с названием, сквозная, в базе УП, включена), ``disciplines``, ``branch_status``;
* ``nodes`` — все живые узлы с O/R/P, ×N, позицией, названием и типом (с названием), строками
  комментария, автором и временем последней правки, а также посчитанным E узла;
* ``types``, ``tags``, ``users`` — денормализованные названия справочников и людей;
* ``totals`` и ``pm`` — итоги E/σ/P80/P90 и часы УП;
* ``customer_questions`` — открытые на момент снимка вопросы заказчику (номер, узел, статус).

Обсуждений и заметок в снимке нет (FR-NOTE-01). Деньги (ставки, валюта, курс, НДС) — в
``money_payload`` через сервис денег; список отдаёт «в КП» в валюте только с ``money.read``.
``payload_sha256`` — SHA-256 канонического JSON ``payload``. Правка и удаление невозможны
(триггер БД, DB-008); единственное изменение — пометка «ошибочный» (повтор — 409
``INVALID_TRANSITION``). Создание и пометка — в аудит.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ThreadStatus, UserStatus
from estimator.db.models.dictionaries import CommentTag, NodeType
from estimator.db.models.discussions import Thread
from estimator.db.models.files import Snapshot
from estimator.db.models.projects import Project
from estimator.db.models.users import User
from estimator.db.uuid7 import uuid7
from estimator.domain import calc
from estimator.security import audit
from estimator.services.common import hours, user_ref
from estimator.services.money import snapshot as snapshot_money
from estimator.services.tree.edit import invalid
from estimator.services.tree.load import compute

SCHEMA = 1


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _tag_ids(lines: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for line in lines:
        if isinstance(line, Mapping) and isinstance(line.get("tag_id"), str):
            out.add(line["tag_id"])
    return out


def figures(totals: calc.Totals | calc.Figures) -> dict[str, str | None]:
    return {
        "e": hours(totals.e),
        "sigma": hours(totals.sigma),
        "p80": hours(totals.p80),
        "p90": hours(totals.p90),
    }


async def _names(db: AsyncSession, key: Any, name: Any, ids: set[Any]) -> dict[Any, str]:
    if not ids:
        return {}
    return dict((await db.execute(select(key, name).where(key.in_(ids)))).all())


async def capture(db: AsyncSession, project: Project) -> dict[str, Any]:
    """``payload`` снимка из текущего состояния проекта (без денег)."""
    computed = await compute(db, project)
    result = computed.result
    nodes = computed.nodes
    type_ids = {n.type_id for n in nodes if n.type_id}
    types = await _names(db, NodeType.id, NodeType.name, type_ids)
    tag_ids = _tag_ids(line for n in nodes for line in (n.comment_lines or []))
    tags: dict[Any, str] = {}
    if tag_ids:
        valid = set()
        for t in tag_ids:
            try:
                valid.add(uuid.UUID(t))
            except ValueError:
                continue
        tags = await _names(db, CommentTag.id, CommentTag.name, valid)
    user_ids = {n.updated_by for n in nodes if n.updated_by}
    users = await _names(db, User.id, User.full_name, user_ids)
    questions = (
        await db.execute(
            select(Thread.id, Thread.customer_question_no, Thread.node_id, Thread.customer_status)
            .where(
                Thread.project_id == project.id,
                Thread.is_customer,
                Thread.status == ThreadStatus.OPEN,
            )
            .order_by(Thread.customer_question_no)
        )
    ).all()
    tree = result.tree.nodes
    return {
        "schema": SCHEMA,
        "project": {
            "name": project.name,
            "customer": project.customer,
            "status": str(project.status),
            "pm_percent": format_decimal(project.pm_percent),
            "pm_percent_reason": project.pm_percent_reason,
            "detail_level": str(project.detail_level),
            "quote_figure": str(project.quote_figure),
            "duration_weeks": project.duration_weeks,
            "deadline": None if project.deadline is None else project.deadline.isoformat(),
        },
        "phases": [
            {
                "id": str(p.phase_id),
                "name": p.name,
                "is_cross_cutting": p.is_cross_cutting,
                "in_pm_base": p.in_pm_base,
                "enabled": p.is_enabled,
            }
            for p in computed.phases
        ],
        "disciplines": [{"id": str(d.discipline_id), "name": d.name} for d in computed.disciplines],
        "branch_status": [
            {
                "phase_id": str(b.phase_id),
                "discipline_id": str(b.discipline_id),
                "status": str(b.status),
            }
            for b, _, _ in computed.status_rows
        ],
        "nodes": [
            {
                "id": str(n.id),
                "parent_id": _id(n.parent_id),
                "kind": str(n.kind),
                "phase_id": str(n.phase_id),
                "discipline_id": _id(n.discipline_id),
                "type_id": _id(n.type_id),
                "title": n.title,
                "position": n.position,
                "o": _dec(n.o),
                "r": _dec(n.r),
                "p": _dec(n.p),
                "multiplier": n.multiplier,
                "comment_lines": n.comment_lines,
                "updated_by": _id(n.updated_by),
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
                "e": hours(tree[str(n.id)].totals.e) if str(n.id) in tree else None,
            }
            for n in nodes
        ],
        "types": {str(k): v for k, v in types.items()},
        "tags": {str(k): v for k, v in tags.items()},
        "users": {str(k): v for k, v in users.items()},
        "totals": figures(result.total),
        "pm": {"e": hours(result.pm.e), "percent": format_decimal(project.pm_percent)},
        "customer_questions": [
            {"thread_id": str(t), "no": no, "node_id": _id(node), "status": str(status)}
            for t, no, node, status in questions
        ],
    }


def project_input(payload: Mapping[str, Any]) -> calc.ProjectInput:
    """Вход расчёта из ``payload`` (тот же формат, что строит :func:`capture`)."""
    p = payload["project"]
    return calc.ProjectInput(
        pm_percent=Decimal(p["pm_percent"]),
        quote_figure=calc.QuoteFigure(p["quote_figure"]),
        detail_level=calc.DetailLevel(p["detail_level"]),
        phases=[
            calc.Phase(
                id=ph["id"],
                name=ph["name"],
                is_cross_cutting=ph["is_cross_cutting"],
                in_pm_base=ph["in_pm_base"],
                enabled=ph["enabled"],
            )
            for ph in payload["phases"]
        ],
        disciplines=[calc.Discipline(id=d["id"], name=d["name"]) for d in payload["disciplines"]],
        nodes=[
            calc.Node(
                id=n["id"],
                parent_id=n["parent_id"],
                kind=calc.NodeKind(n["kind"]),
                phase_id=n["phase_id"],
                discipline_id=n["discipline_id"],
                type=n["type_id"],
                title=n["title"],
                o=None if n["o"] is None else Decimal(n["o"]),
                r=None if n["r"] is None else Decimal(n["r"]),
                p=None if n["p"] is None else Decimal(n["p"]),
                multiplier=n["multiplier"],
            )
            for n in payload["nodes"]
        ],
        branch_status={
            (b["phase_id"], b["discipline_id"]): calc.BranchStatus(b["status"])
            for b in payload["branch_status"]
        },
    )


def recalc(payload: Mapping[str, Any]) -> calc.ProjectResult:
    return calc.calculate(project_input(payload))


def digest(payload: Mapping[str, Any]) -> bytes:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).digest()


async def _authors(db: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Any]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.full_name, User.status).where(User.id.in_(wanted)))
    return {
        i: user_ref(i, name, is_active=status is UserStatus.ACTIVE)
        for i, name, status in rows.all()
    }


async def snapshots_out(
    db: AsyncSession, snapshots: list[Snapshot], *, with_money: bool
) -> list[dict[str, Any]]:
    """``Snapshot`` контракта; ``money`` («в КП» в валюте) — только с ``money.read``."""
    authors = await _authors(db, (s.created_by for s in snapshots))
    money = (
        await snapshot_money.stored_payloads(db, [s.id for s in snapshots]) if with_money else {}
    )
    out: list[dict[str, Any]] = []
    for s in snapshots:
        item: dict[str, Any] = {
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "created_by": authors.get(s.created_by) or user_ref(s.created_by, "?"),
            "created_at": s.created_at,
            "is_invalid": s.is_invalid,
            "project_version": s.project_version,
            "totals": {k: v for k, v in s.payload["totals"].items() if v is not None},
        }
        if with_money:
            raw = money.get(s.id)
            figure = None if raw is None else snapshot_money.quote(recalc(s.payload), raw)
            item["money"] = {
                "currency": "RUB" if raw is None else raw["currency"],
                "quote_cur": None
                if figure is None or figure.total_cur is None
                else format_decimal(figure.total_cur),
            }
        out.append(item)
    return out


async def list_snapshots(db: AsyncSession, project_id: uuid.UUID) -> list[Snapshot]:
    return list(
        await db.scalars(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        )
    )


async def create(
    db: AsyncSession, principal: Principal, project: Project, name: str, description: str
) -> Snapshot:
    if not name.strip():
        raise invalid("name", "Укажите название снимка")
    payload = await capture(db, project)
    sha = digest(payload)
    snapshot = Snapshot(
        id=uuid7(),
        project_id=project.id,
        name=name.strip(),
        description=description,
        project_version=project.version,
        created_by=principal.user_id,
        payload=payload,
        money_payload=await snapshot_money.current_payload(db, project.id),
        payload_sha256=sha,
    )
    db.add(snapshot)
    await db.flush()
    await db.refresh(snapshot, ["created_at", "is_invalid"])
    await audit.write(
        db, "project.snapshot.created", user_id=principal.user_id, login=principal.login,
        session_id=principal.session_id, object_type="snapshot", object_id=snapshot.id,
        project_id=project.id, details={"payload_sha256": sha.hex()},
    )  # fmt: skip
    return snapshot


async def invalidate(db: AsyncSession, principal: Principal, snapshot: Snapshot) -> Snapshot:
    if snapshot.is_invalid:
        raise ApiError("INVALID_TRANSITION", detail="Снимок уже помечен «ошибочный»")
    snapshot.is_invalid = True
    snapshot.invalidated_by = principal.user_id
    snapshot.invalidated_at = dt.datetime.now(dt.UTC)
    await db.flush()
    await audit.write(
        db, "project.snapshot.invalidated", user_id=principal.user_id, login=principal.login,
        session_id=principal.session_id, object_type="snapshot", object_id=snapshot.id,
        project_id=snapshot.project_id, details={},
    )  # fmt: skip
    return snapshot
