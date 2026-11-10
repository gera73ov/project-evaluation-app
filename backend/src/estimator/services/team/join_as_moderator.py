"""«Стать модератором проекта» (CORE-071; SPEC FR-PORT-03, R-06, 3.3, 3.4, SEC-AUTHZ-05, G-21;
15.2 ``POST /projects/{id}/join-as-moderator``).

Руководитель пресейла добавляет модератором только себя, в любом статусе, кроме «Архива»
(409 ``PROJECT_STATUS_CONFLICT``). Системная роль «Модератор» для этого не нужна (R-06). Уже
модератор — повтор ничего не меняет. Действующие модераторы получают «Руководитель пресейла вошёл
модератором»; аудит — ``project.joined_as_moderator`` и ``project.team.changed``
(``via: join_as_moderator``). Дальше действуют права модератора проекта; выйти из команды можно,
если он не последний модератор; добавить других модераторов или передать проект — нельзя
(:func:`estimator.services.team.check_presale_head_limits`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ProjectRole, ProjectStatus, UserStatus
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User
from estimator.notifications import inapp
from estimator.security import audit
from estimator.services import team
from estimator.services.projects import journal


async def join(db: AsyncSession, principal: Principal, project: Project) -> list[dict[str, Any]]:
    if ProjectStatus(project.status) is ProjectStatus.ARCHIVED:
        raise ApiError(
            "PROJECT_STATUS_CONFLICT",
            detail="Проект в «Архиве»: стать модератором нельзя",
            status=ProjectStatus.ARCHIVED.value,
        )
    rows = await team._rows(db, project.id)
    if any(r.user_id == principal.user_id and r.role == ProjectRole.MODERATOR for r in rows):
        return await team.members_out(db, project.id)
    moderators = list(
        await db.scalars(
            select(ProjectMember.user_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.role == ProjectRole.MODERATOR,
                User.status == UserStatus.ACTIVE,
            )
        )
    )
    row = ProjectMember(
        project_id=project.id,
        user_id=principal.user_id,
        role=ProjectRole.MODERATOR,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(row)
    await db.flush()
    await audit.write(
        db, "project.joined_as_moderator", user_id=principal.user_id, login=principal.login,
        session_id=principal.session_id, object_type="project", object_id=project.id,
        project_id=project.id, details={},
    )  # fmt: skip
    await team._audit_row(db, principal, project.id, row, "added", "join_as_moderator")
    key = team._journal_key(team._key(row))
    journal.record(
        db, project.id, principal.user_id, "project.team", {key: (None, team._state(row))}
    )
    await inapp.notify(
        db, "presale_head_joined", moderators, project_id=project.id,
        payload={"project_id": str(project.id), "actor_id": str(principal.user_id)},
        actor_id=principal.user_id,
    )  # fmt: skip
    await team.refresh_no_moderator(db, project)
    await team._announce(db, project, added=[principal.user_id], removed=[], updated=[])
    return await team.members_out(db, project.id)
