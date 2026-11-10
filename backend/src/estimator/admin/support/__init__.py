"""Режим поддержки (ADM-011; SPEC FR-ADM-06, Q-15, BR-ADM-03, SEC-AUTHZ-05, TC-ADM-02;
contracts/openapi.yaml ``POST /admin/projects/{id}/support-session``).

Администратор с причиной 10–500 символов открывает проект на чтение не дольше чем на 60 минут, в
любом статусе. Права на время сессии даёт контекст ``support_session`` (permissions.yaml):
чтение проекта, дерева, обсуждений, журнала, статистики, вопросов заказчику и снимков — без
денег, закрытых заметок и записи (SEC-005). Повторное открытие того же проекта закрывает прежнюю
сессию и начинает новую на 60 минут. Открытие — аудит ``project.support_session.opened`` с
причиной и уведомление модераторам проекта «Администратор открыл проект в режиме поддержки:
<причина>» в любом статусе, включая «Подготовку» и «Архив».
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ProjectRole
from estimator.db.models.projects import Project, ProjectMember, SupportSession
from estimator.notifications import inapp
from estimator.security import audit

DURATION = dt.timedelta(minutes=60)
REASON_MIN, REASON_MAX = 10, 500


def _iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def open_session(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID, reason: str
) -> dict[str, Any]:
    text = reason.strip()
    if not REASON_MIN <= len(text) <= REASON_MAX:
        raise ApiError(
            "VALIDATION_FAILED",
            detail=f"Причина — от {REASON_MIN} до {REASON_MAX} символов",
            errors=[{"field": "/reason", "code": "length",
                     "message": f"От {REASON_MIN} до {REASON_MAX} символов"}],
        )  # fmt: skip
    if await db.get(Project, project_id) is None:
        raise ApiError("NOT_FOUND")
    now = dt.datetime.now(dt.UTC)
    await db.execute(
        update(SupportSession)
        .where(
            SupportSession.admin_id == principal.user_id,
            SupportSession.project_id == project_id,
            SupportSession.ended_at.is_(None),
            SupportSession.expires_at > now,
        )
        .values(ended_at=now)
    )
    session = SupportSession(
        admin_id=principal.user_id,
        project_id=project_id,
        reason=text,
        started_at=now,
        expires_at=now + DURATION,
    )
    db.add(session)
    await db.flush()
    await audit.write(
        db, "project.support_session.opened", user_id=principal.user_id, login=principal.login,
        session_id=principal.session_id, object_type="support_session", object_id=session.id,
        project_id=project_id, details={"reason": text, "expires_at": _iso(session.expires_at)},
    )  # fmt: skip
    moderators = await db.scalars(
        select(ProjectMember.user_id).where(
            ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.MODERATOR
        )
    )
    await inapp.notify(
        db, "support_session_opened", set(moderators), project_id=project_id,
        payload={"project_id": str(project_id), "actor_id": str(principal.user_id),
                 "support_session_id": str(session.id), "reason": text},
        actor_id=principal.user_id,
    )  # fmt: skip
    return {"id": session.id, "project_id": project_id, "expires_at": _iso(session.expires_at)}
