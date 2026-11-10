"""Реестры проектов (ADM-005, ADM-010; SPEC 3.2, 7.5 «Реестр проектов», BR-PRJ-07, CL-09).

Строка реестра — ``RegistryProject`` контракта: название, заказчик, модераторы, статус, даты,
признак «без модератора» с числом дней. Денег, дерева и обсуждений в реестре нет (FR-ADM-06,
BR-ADM-03). Порядок — сначала новые (``created_at`` по убыванию, затем ``id``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.enums import ProjectRole, ProjectStatus, UserStatus
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User
from estimator.services.common import user_ref


@dataclass(frozen=True)
class Filter:
    q: str | None = None
    status: ProjectStatus | None = None
    without_moderator: bool | None = None


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def days_since(moment: dt.datetime | None, now: dt.datetime | None = None) -> int | None:
    """Полных суток без модератора (BR-PRJ-07)."""
    if moment is None:
        return None
    return max(0, int(((now or dt.datetime.now(dt.UTC)) - moment).total_seconds() // 86400))


async def moderators(
    db: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    out: dict[uuid.UUID, list[dict[str, Any]]] = {pid: [] for pid in project_ids}
    if not project_ids:
        return out
    rows = await db.execute(
        select(ProjectMember.project_id, User.id, User.full_name, User.status)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.role == ProjectRole.MODERATOR,
        )
        .order_by(User.full_name, User.id)
    )
    for project_id, user_id, name, status in rows.all():
        out[project_id].append(user_ref(user_id, name, is_active=status == UserStatus.ACTIVE))
    return out


def project_out(project: Project, mods: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "customer": project.customer,
        "moderators": mods,
        "status": project.status.value,
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
        "no_moderator_since": _iso(project.no_moderator_since),
        "days_without_moderator": days_since(project.no_moderator_since),
    }


async def page(
    db: AsyncSession, filt: Filter, *, after: dict[str, Any] | None, limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Страница реестра и позиция следующей (или ``None``)."""
    stmt = select(Project)
    if filt.q and filt.q.strip():
        pattern = _like(filt.q.strip())
        stmt = stmt.where(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                Project.customer.ilike(pattern, escape="\\"),
            )
        )
    if filt.status is not None:
        stmt = stmt.where(Project.status == filt.status)
    if filt.without_moderator is True:
        stmt = stmt.where(Project.no_moderator_since.is_not(None))
    elif filt.without_moderator is False:
        stmt = stmt.where(Project.no_moderator_since.is_(None))
    if after is not None:
        try:
            moment = dt.datetime.fromisoformat(str(after["c"]))
            last = uuid.UUID(str(after["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("CURSOR_INVALID") from exc
        if moment.tzinfo is None:
            raise ApiError("CURSOR_INVALID")
        stmt = stmt.where(
            or_(Project.created_at < moment, (Project.created_at == moment) & (Project.id < last))
        )
    stmt = stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)
    rows = list(await db.scalars(stmt))
    items, more = rows[:limit], len(rows) > limit
    mods = await moderators(db, [p.id for p in items])
    nxt = {"c": items[-1].created_at.isoformat(), "id": str(items[-1].id)} if more else None
    return [project_out(p, mods[p.id]) for p in items], nxt
