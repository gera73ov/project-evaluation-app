"""CORE-033 · «Мои оценки»: список проектов пользователя (SPEC FR-HOME-01, FR-HOME-02, FR-HOME-04,
11.3 №1–7, BR-PRJ-08, Q-43, Q-44, 3.4; 15.2 ``GET /projects``).

* Проекты, где пользователь участник в любой проектной роли. В «Подготовке» — только где он
  модератор (3.4, M3.4-01); «Архив» — только по фильтру ``status=archived`` (Q-44).
* Мой прогресс — ветки «готово» или «не нужно» из всех моих: у эксперта — пары «включённая фаза ×
  его дисциплина», у модератора и пресейла — все ветки проекта. В «Подготовке» без экспертов —
  ``null`` («команда не назначена»).
* Дедлайн красный, если до него ≤ 2 рабочих дней по производственному календарю (BR-PRJ-08) и
  мои ветки не готовы. «Мне» — непрочитанные уведомления о вопросах мне, ответах на мои вопросы,
  перенаправленных мне вопросах и изменениях модератора в моих листьях.
* «Итог» — «Цифра для КП» в часах из кэша ``project_totals`` (CORE-026); сумма «в КП» в валюте —
  только в проектах, где пользователь модератор или пресейл и TOTP в сессии пройден (``money.read``,
  FR-HOME-04, SEC-AUTHZ-05).
* Сортировка: сначала с «Мне» > 0, затем по дедлайну (без дедлайна — в конце), затем по названию.
  Курсор — ключ сортировки последней строки.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.calendar import working_days
from estimator.api.common.decimal import format_decimal
from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue, ProjectRole, ProjectStatus
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import BranchStatus, Project, ProjectMember, ProjectPhase
from estimator.db.models.tree import ChangeLog
from estimator.services.common import app_today, hours
from estimator.services.money.totals import CachedTotals, cached

ALERT_DAYS = 2  # BR-PRJ-08
MIN_QUERY = 2
#: Виды уведомлений счётчика «Мне» (11.3 №5)
TO_ME = ("question_to_me", "answer_to_my_question", "question_redirected", "moderator_change")
_DONE = {BranchStatusValue.DONE, BranchStatusValue.NOT_NEEDED}
_MONEY_ROLES = {ProjectRole.MODERATOR, ProjectRole.PRESALE}
_NO_DEADLINE = "9999-12-31"


@dataclass(frozen=True)
class HomeFilter:
    status: ProjectStatus | None = None
    role: ProjectRole | None = None
    q: str | None = None


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _memberships(
    db: AsyncSession, user_id: uuid.UUID, flt: HomeFilter
) -> tuple[list[Project], dict[uuid.UUID, list[ProjectMember]]]:
    moderator_of = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user_id, ProjectMember.role == ProjectRole.MODERATOR
    )
    query = (
        select(Project)
        .where(
            Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            ),
            or_(Project.status != ProjectStatus.PREPARATION, Project.id.in_(moderator_of)),
        )
        .order_by(Project.id)
    )
    if flt.status is not None:
        query = query.where(Project.status == flt.status)
    else:
        query = query.where(Project.status != ProjectStatus.ARCHIVED)
    if flt.role is not None:
        query = query.where(
            Project.id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user_id, ProjectMember.role == flt.role
                )
            )
        )
    q = (flt.q or "").strip()
    if len(q) >= MIN_QUERY:
        pattern = _like(q)
        query = query.where(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                Project.customer.ilike(pattern, escape="\\"),
            )
        )
    projects = list((await db.scalars(query)).all())
    members: dict[uuid.UUID, list[ProjectMember]] = {}
    if projects:
        rows = await db.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.project_id.in_([p.id for p in projects]),
            )
            .order_by(ProjectMember.role, ProjectMember.discipline_id)
        )
        for m in rows:
            members.setdefault(m.project_id, []).append(m)
    return projects, members


async def _branches(
    db: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, BranchStatusValue]]]:
    """Ветки включённых фаз: проект → [(дисциплина, статус)]."""
    out: dict[uuid.UUID, list[tuple[uuid.UUID, BranchStatusValue]]] = {}
    if not project_ids:
        return out
    rows = await db.execute(
        select(BranchStatus.project_id, BranchStatus.discipline_id, BranchStatus.status)
        .join(
            ProjectPhase,
            and_(
                ProjectPhase.project_id == BranchStatus.project_id,
                ProjectPhase.phase_id == BranchStatus.phase_id,
            ),
        )
        .where(BranchStatus.project_id.in_(project_ids), ProjectPhase.is_enabled.is_(True))
    )
    for pid, discipline_id, status in rows:
        out.setdefault(pid, []).append((discipline_id, status))
    return out


async def _has_experts(db: AsyncSession, project_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not project_ids:
        return set()
    rows = await db.scalars(
        select(ProjectMember.project_id)
        .where(ProjectMember.project_id.in_(project_ids), ProjectMember.role == ProjectRole.EXPERT)
        .distinct()
    )
    return set(rows.all())


async def _to_me(
    db: AsyncSession, user_id: uuid.UUID, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    rows = await db.execute(
        select(Notification.project_id, func.count())
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.kind.in_(TO_ME),
            Notification.project_id.in_(project_ids),
        )
        .group_by(Notification.project_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


async def _changed_at(db: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not project_ids:
        return {}
    rows = await db.execute(
        select(ChangeLog.project_id, func.max(ChangeLog.created_at))
        .where(ChangeLog.project_id.in_(project_ids))
        .group_by(ChangeLog.project_id)
    )
    return dict(rows.all())


def _progress(
    project: Project,
    roles: list[ProjectMember],
    branches: list[tuple[uuid.UUID, BranchStatusValue]],
    has_experts: bool,
) -> dict[str, int] | None:
    if project.status is ProjectStatus.PREPARATION and not has_experts:
        return None  # «команда не назначена»
    if any(m.role is not ProjectRole.EXPERT for m in roles):
        mine = branches
    else:
        disciplines = {m.discipline_id for m in roles}
        mine = [b for b in branches if b[0] in disciplines]
    return {"done": sum(1 for _, st in mine if st in _DONE), "total": len(mine)}


def _quote_hours(project: Project, totals: CachedTotals | None) -> str | None:
    if totals is None or not totals.e:
        return None  # в «Подготовке» без оценок — «—» (11.3 №7)
    value = {"e": totals.e, "p80": totals.p80, "p90": totals.p90}[str(project.quote_figure)]
    return hours(value)


def _money(value: Any) -> str | None:
    return None if value is None else format_decimal(value)


def _sort_key(item: Mapping[str, Any]) -> list[Any]:
    return [
        0 if item["questions_to_me"] > 0 else 1,
        item["deadline"] or _NO_DEADLINE,
        item["name"],
        item["id"],
    ]


async def my_projects(
    db: AsyncSession,
    principal: Principal,
    flt: HomeFilter,
    *,
    after: list[Any] | None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[Any] | None]:
    """Страница «Моих оценок» и ключ последней строки, если есть следующая страница."""
    projects, members = await _memberships(db, principal.user_id, flt)
    ids = [p.id for p in projects]
    money_ids = (
        {pid for pid, ms in members.items() if any(m.role in _MONEY_ROLES for m in ms)}
        if principal.mfa_passed
        else set()
    )
    totals = await cached(db, ids, money_ids)
    branches = await _branches(db, ids)
    experts = await _has_experts(db, ids)
    to_me = await _to_me(db, principal.user_id, ids)
    changed = await _changed_at(db, ids)
    today = await app_today(db)

    items: list[dict[str, Any]] = []
    for p in projects:
        roles = members.get(p.id, [])
        progress = _progress(p, roles, branches.get(p.id, []), p.id in experts)
        alert = False
        if p.deadline is not None and progress is not None and progress["done"] < progress["total"]:
            alert = p.deadline <= today or await working_days(db, today, p.deadline) <= ALERT_DAYS
        row = totals.get(p.id)
        item: dict[str, Any] = {
            "id": str(p.id),
            "name": p.name,
            "customer": p.customer,
            "status": str(p.status),
            "my_roles": [
                {
                    "role": str(m.role),
                    "discipline_id": None if m.discipline_id is None else str(m.discipline_id),
                    "is_reviewer": m.is_reviewer,
                }
                for m in roles
            ],
            "my_progress": progress,
            "deadline": None if p.deadline is None else p.deadline.isoformat(),
            "deadline_alert": alert,
            "questions_to_me": to_me.get(p.id, 0),
            "updated_at": max(_dates(p.updated_at, changed.get(p.id))),
            "quote_figure": str(p.quote_figure),
            "quote_hours": _quote_hours(p, row),
        }
        if row is not None and row.money is not None:
            item["money"] = {
                "currency": row.money.currency,
                "quote_cur": _money(row.money.quote_cur),
                "quote_rub": _money(row.money.quote_rub),
                "rates_missing": row.money.rates_missing,
            }
        items.append(item)

    items.sort(key=_sort_key)
    if after is not None:
        items = [i for i in items if _sort_key(i) > after]
    page = items[:limit]
    more = len(items) > limit
    return page, (_sort_key(page[-1]) if more and page else None)


def _dates(*values: dt.datetime | None) -> Iterable[dt.datetime]:
    return [v for v in values if v is not None]
