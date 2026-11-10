"""ADM-012 · «Заменить участника» во всех проектах (SPEC FR-ADM-05, Q-29, TC-ADM-01, G-20;
15.2 ``POST /admin/users/{id}/replace``).

* ``dry_run`` (по умолчанию) — список активных проектов исходного пользователя (кроме «Архива»)
  с его ролями, дисциплинами и ревьюерством, числом открытых адресованных ему обсуждений и
  проверкой системных ролей замены: модератор проекта — «Модератор» или «Руководитель
  пресейла», пресейл — «Пресейл». Строка без нужной роли — ``applicable: false`` и ``problem``.
* Подтверждение (``dry_run: false``, ``project_ids`` — отмеченные проекты из списка): в каждом
  применимом проекте замена получает те же строки, исходный исключается, открытые вопросы
  переадресуются замене с событием в ленте, модераторы и замена получают уведомления — общий код
  с заменой в одном проекте (:func:`estimator.services.team.transfer`). Неприменимые строки
  пропускаются. Проект не из списка — 422. Исходный пользователь не обязан быть заблокирован
  («обычно заблокированного»). Итог — аудит ``users.replaced_everywhere``.
* Учётки администраторов и скрытые роли — 404, как во всей админке пользователей (ADM-006).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.users import _load
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import AddresseeType, ProjectStatus, ThreadStatus, UserStatus
from estimator.db.models.discussions import Message, MessageAddressee, Thread
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User
from estimator.security import audit
from estimator.security.authz import role_rules
from estimator.services import team


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": field, "code": "invalid", "message": message}],
    )


async def _open_questions(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Thread.project_id, func.count(func.distinct(Thread.id)))
        .join(Message, and_(Message.thread_id == Thread.id, Message.needs_answer))
        .join(MessageAddressee, MessageAddressee.message_id == Message.id)
        .where(
            Thread.status == ThreadStatus.OPEN,
            MessageAddressee.target_type == AddresseeType.USER,
            MessageAddressee.target_id == user_id,
        )
        .group_by(Thread.project_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


async def _plan(
    db: AsyncSession, user_id: uuid.UUID, replacement_id: uuid.UUID
) -> list[tuple[Project, list[ProjectMember], str | None]]:
    rows = await db.execute(
        select(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user_id, Project.status != ProjectStatus.ARCHIVED)
        .order_by(Project.name, Project.id)
    )
    by_project: dict[uuid.UUID, list[ProjectMember]] = defaultdict(list)
    projects: dict[uuid.UUID, Project] = {}
    for member, project in rows.all():
        by_project[project.id].append(member)
        projects[project.id] = project
    roles = (await team._system_roles(db, [replacement_id]))[replacement_id]
    return [
        (projects[pid], members, team.replacement_problem(roles, members))
        for pid, members in by_project.items()
    ]


_PROBLEM = {
    "moderator": "replacement_lacks_moderator_role",
    "presale": "replacement_lacks_presale_role",
}


def _report(
    plan: Sequence[tuple[Project, list[ProjectMember], str | None]], questions: dict[uuid.UUID, int]
) -> list[dict[str, Any]]:
    return [
        {
            "project_id": str(project.id),
            "name": project.name,
            "roles": [
                {
                    "role": str(m.role),
                    "discipline_id": None if m.discipline_id is None else str(m.discipline_id),
                    "is_reviewer": m.is_reviewer,
                }
                for m in members
            ],
            "applicable": problem is None,
            "problem": None if problem is None else _PROBLEM[problem],
            "open_questions": questions.get(project.id, 0),
        }
        for project, members, problem in plan
    ]


async def replace_everywhere(
    db: AsyncSession,
    actor: Principal,
    user_id: uuid.UUID,
    replacement_id: uuid.UUID,
    *,
    dry_run: bool = True,
    project_ids: Sequence[uuid.UUID] | None = None,
) -> dict[str, Any]:
    await _load(db, user_id)
    if replacement_id == user_id:
        raise _invalid("/replacement_user_id", "Замена совпадает с исходным пользователем")
    replacement = await db.get(User, replacement_id)
    if replacement is None or replacement.status in (UserStatus.BLOCKED, UserStatus.ANONYMIZED):
        raise _invalid("/replacement_user_id", "Замена должна быть незаблокированным пользователем")
    roles = (await team._system_roles(db, [replacement_id]))[replacement_id]
    if roles & role_rules.NO_PROJECTS:
        raise _invalid("/replacement_user_id", "Этого пользователя нельзя назначить в проект")

    plan = await _plan(db, user_id, replacement_id)
    report = _report(plan, await _open_questions(db, user_id))
    if dry_run:
        return {"projects": report, "applied": False}

    chosen = set(project_ids or ())
    unknown = chosen - {p.id for p, _, _ in plan}
    if unknown:
        raise _invalid("/project_ids", "Проект не из списка замены")
    applied = skipped = redirected = 0
    for project, members, problem in plan:
        if project.id not in chosen:
            continue
        if problem is not None:
            skipped += 1
            continue
        _, count = await team.transfer(
            db, actor, project, user_id, replacement_id, members, "replace"
        )
        applied += 1
        redirected += count
    await audit.write(
        db, "users.replaced_everywhere", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user_id,
        details={"replacement_user_id": str(replacement_id), "projects_applied": applied,
                 "projects_skipped": skipped, "questions_redirected": redirected},
    )  # fmt: skip
    return {"projects": report, "applied": True}
