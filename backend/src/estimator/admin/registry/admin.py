"""Реестр проектов администратора (ADM-010; SPEC 7.5 «Реестр проектов», BR-PRJ-07, Q-30,
BR-ADM-03, Q-25; openapi.yaml ``GET /admin/projects``, ``POST /admin/projects/{id}/moderators``).

«Передать / добавить модератора»: добавляются пользователи с системной ролью «Модератор»
(иначе 409 ``MEMBER_ROLE_REQUIRED``), снимаются строки «модератор» указанных пользователей; без
модератора проект не остаётся (409 ``LAST_MODERATOR``). Изменение идёт через команду проекта
(CORE-012): аудит ``project.team.changed`` с ``via = transfer`` и пометкой
``added_by_admin_self``, когда администратор назначил себя (Q-25), журнал, ``member.updated``,
«Вас назначили» и пересчёт ``no_moderator_since``. Проект в любом статусе.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ProjectRole
from estimator.db.models.projects import Project, ProjectMember
from estimator.services import team


async def transfer_moderators(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    add: Iterable[uuid.UUID],
    remove: Iterable[uuid.UUID],
) -> list[dict[str, Any]]:
    project = await db.get(Project, project_id, with_for_update=True)
    if project is None:
        raise ApiError("NOT_FOUND")
    add_ids, remove_ids = set(add), set(remove)
    if add_ids & remove_ids:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Один пользователь и добавляется, и снимается",
            errors=[{"field": "/remove_user_ids", "code": "invalid",
                     "message": "Пользователь есть и в add_user_ids"}],
        )  # fmt: skip
    rows = list(
        await db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id))
    )
    specs = [
        team.MemberSpec(r.user_id, ProjectRole(r.role), r.discipline_id, r.is_reviewer)
        for r in rows
        if not (ProjectRole(r.role) is ProjectRole.MODERATOR and r.user_id in remove_ids)
    ]
    present = {s.user_id for s in specs if s.role is ProjectRole.MODERATOR}
    specs += [
        team.MemberSpec(uid, ProjectRole.MODERATOR) for uid in sorted(add_ids - present, key=str)
    ]
    await team.put_members(db, principal, project, specs, via="transfer")
    return await team.members_out(db, project_id)
