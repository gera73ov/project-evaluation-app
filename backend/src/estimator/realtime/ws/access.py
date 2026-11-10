"""Проверки WebSocket: рукопожатие и права на проект (RT-003; SEC-AUTHZ-01, SEC-WEB-04, FR-SA-06).

* :func:`handshake` — сессия из cookie (без продления, FR-SESS-02), полная сессия после смены
  пароля и подключения TOTP, мастер настройки завершён, для суперадминистратора — сеть из
  ``security.admin_networks``. Отказ — :class:`HandshakeDenied` с кодом и HTTP-статусом.
* :func:`project_access` — право ``tree.read`` на проекте по актуальным данным (членство, режим
  поддержки, руководитель пресейла, статус проекта M3.4-01) и, при праве и пройденном TOTP,
  каналы ``:money`` и ``:notes``. Используется при ``subscribe`` и при каждой перепроверке.
* :func:`revoke_reason` — почему доступ к проекту пропал (``access.revoked.reason``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from estimator.auth.context import Principal, UnauthenticatedError, resolve_principal
from estimator.auth.sessions import SessionService, session_id_from
from estimator.auth.setup_gate import ensure_setup_allows
from estimator.db.enums import ProjectStatus
from estimator.db.models.projects import Project, ProjectMember
from estimator.realtime.ws.hub import ProjectAccess
from estimator.security.audit import security_events
from estimator.security.authz import deps as authz_deps
from estimator.security.authz.engine import AccessDenied, Target, decide_any
from estimator.security.networks import address_allowed, load_admin_networks
from estimator.security.ratelimit.limiter import client_ip

READ_PERMISSION = "tree.read"


class HandshakeDenied(Exception):
    """Рукопожатие отклонено: ответ HTTP с кодом из contracts/errors.yaml."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def handshake(ws: WebSocket, db: AsyncSession, service: SessionService) -> Principal:
    try:
        principal = await resolve_principal(ws, db, service, session_id_from(ws), touch=False)  # type: ignore[arg-type]
    except UnauthenticatedError:
        raise HandshakeDenied("UNAUTHENTICATED") from None
    try:
        await ensure_setup_allows(db, superadmin=principal.is_superadmin)
    except HTTPException as exc:
        raise HandshakeDenied(str(exc.detail["code"])) from None  # type: ignore[index]
    if principal.password_change_required:
        raise HandshakeDenied("PASSWORD_CHANGE_REQUIRED")
    if principal.enrollment_required:
        raise HandshakeDenied("TOTP_ENROLL_REQUIRED")
    if principal.is_superadmin:
        ip = client_ip(ws)  # type: ignore[arg-type]
        if not address_allowed(ip, await load_admin_networks(db)):
            await security_events.network_denied(
                db, ws.app.state.redis, user_id=principal.user_id, login=principal.login, ip=ip,
                session_id=principal.session_id, route=ws.url.path,
            )  # fmt: skip
            raise HandshakeDenied("NOT_FOUND")
    return principal


def authorizer(
    ws: WebSocket, principal: Principal, db: AsyncSession, redis: Redis
) -> authz_deps.Authorizer:
    return authz_deps.Authorizer(ws, principal, db, redis)  # type: ignore[arg-type]


async def project_access(
    ws: WebSocket,
    principal: Principal,
    db: AsyncSession,
    redis: Redis,
    project_id: uuid.UUID,
    *,
    audited: bool = True,
) -> ProjectAccess:
    """Каналы проекта, положенные пользователю сейчас; отказ — ``HTTPException`` (404/403/409).

    ``audited=True`` (команда ``subscribe``): отказ пишется в аудит так же, как отказ REST
    (``security.access_denied``, не чаще раза в минуту), первое открытие чужого проекта
    руководителем пресейла — ``project.opened_by_presale_head``. Перепроверка прав (RT-008) —
    без аудита: это не попытка доступа пользователя.
    """
    authz = authorizer(ws, principal, db, redis)
    if audited:
        access = await authz.project(project_id, READ_PERMISSION)
    else:
        target = await authz_deps.project_target(db, project_id)
        if target is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND"})
        subject = await authz.subject(project_id, (READ_PERMISSION,))
        try:
            access = decide_any(authz.catalog, subject, (READ_PERMISSION,), target)
        except AccessDenied as exc:
            raise HTTPException(exc.status, detail=exc.detail()) from None
    return ProjectAccess(
        project_id=project_id, money=access.money, notes=access.notes, sources=access.sources
    )


@dataclass(frozen=True)
class ProjectState:
    exists: bool
    status: str | None = None
    version: int = 0


async def project_state(db: AsyncSession, project_id: uuid.UUID) -> ProjectState:
    row = (
        await db.execute(select(Project.status, Project.version).where(Project.id == project_id))
    ).first()
    if row is None:
        return ProjectState(False)
    return ProjectState(True, str(row[0]), int(row[1] or 0))


async def revoke_reason(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    had_support: bool,
) -> str:
    """Причина ``access.revoked`` (contracts/ws-events.schema.json) по текущим данным."""
    state = await project_state(db, project_id)
    if not state.exists:
        return "project_purged"
    if had_support and not principal.in_support(project_id):
        return "support_session_expired"
    roles = (
        await db.scalars(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == principal.user_id,
            )
        )
    ).all()
    if not roles:
        return "removed_from_team"
    if state.status == ProjectStatus.PREPARATION.value and "moderator" not in {
        str(r) for r in roles
    }:
        return "project_hidden"
    return "rights_changed"


# --- RT-005: права на захват ячейки ---


def write_permission(field: str) -> str:
    """Право правки поля: комментарий — ``comment.write``, остальные ячейки — ``tree.write``."""
    return "comment.write" if field == "comment" else "tree.write"


async def node_target(db: AsyncSession, node_id: uuid.UUID) -> Target | None:
    """Узел → проект, статус и дисциплина (тот же загрузчик, что у ``/nodes/{id}``)."""
    from estimator.api.v1.nodes import node_target as load

    return await load(db, node_id)


async def check_silent(
    ws: WebSocket,
    principal: Principal,
    db: AsyncSession,
    redis: Redis,
    code: str,
    target: Target,
) -> None:
    """Проверка права без аудита отказа (перепроверка); отказ — ``HTTPException``."""
    authz = authorizer(ws, principal, db, redis)
    subject = await authz.subject(target.project_id, (code,))
    try:
        decide_any(authz.catalog, subject, (code,), target)
    except AccessDenied as exc:
        raise HTTPException(exc.status, detail=exc.detail()) from None
