"""Контекст запроса: текущий пользователь и сессия (AUTH-003; FR-SESS-05, SEC-AUTHZ-01).

Зависимость :func:`current_principal` на каждом запросе:

1. берёт сессию из Redis по cookie ``__Host-session``; нет записи — 401 ``UNAUTHENTICATED``;
2. истёкшую сессию закрывает в БД и пишет ``auth.session.expired`` (в отдельной транзакции —
   транзакция запроса откатится вместе с ответом 401);
3. читает из БД **актуальные** статус и системные роли пользователя: блокировка, смена ролей
   или удаление действуют на следующем запросе, без ожидания истечения сессии;
4. продлевает сессию, если запрос не помечен ``X-Background: 1``.

Флаги :class:`Principal` (``mfa_passed``, ``step_up_until``, ``enrollment_required``,
``support_projects``) используют проверки прав SEC-005 и шлюзы AUTH-006/007.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import HTTPConnection

from estimator.auth.sessions import (
    RevokeReason,
    SessionRecord,
    SessionService,
    id_hash,
    is_background,
    session_id_from,
)
from estimator.db.enums import SystemRole, UserStatus
from estimator.db.models.projects import SupportSession
from estimator.db.models.users import User, UserRole
from estimator.db.session import DbSession, transaction
from estimator.logging import get_logger
from estimator.redis_client import get_redis
from estimator.security import audit

log = get_logger(__name__)

UNAUTHENTICATED = "UNAUTHENTICATED"


class UnauthenticatedError(HTTPException):
    """401 ``UNAUTHENTICATED`` (contracts/errors.yaml). Тело RFC 9457 строит API-003."""

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(status_code=401, detail={"code": UNAUTHENTICATED})
        #: Почему сессии нет (``idle``, ``absolute``, ``blocked`` …) — для ``session.ended`` RT-008
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    """Аутентифицированный пользователь текущего запроса."""

    user_id: uuid.UUID
    login: str
    full_name: str
    roles: frozenset[SystemRole]
    session_id: str = field(repr=False)
    session: SessionRecord = field(repr=False)
    mfa_passed: bool = False
    step_up_until: datetime | None = None
    enrollment_required: bool = False
    password_change_required: bool = False
    support_projects: frozenset[uuid.UUID] = frozenset()

    @property
    def session_hash(self) -> bytes:
        return id_hash(self.session_id)

    def has_role(self, *roles: SystemRole) -> bool:
        return bool(self.roles & set(roles))

    @property
    def is_superadmin(self) -> bool:
        return SystemRole.SUPERADMIN in self.roles

    def step_up_active(self, now: datetime | None = None) -> bool:
        if self.step_up_until is None:
            return False
        return (now or datetime.now(UTC)) < self.step_up_until

    def in_support(self, project_id: uuid.UUID) -> bool:
        """Администратор в режиме поддержки этого проекта (FR-ADM-06)."""
        return project_id in self.support_projects


def get_session_service(request: Request) -> SessionService:
    """Сервис сессий процесса; тесты подменяют зависимость (часы, Redis)."""
    clock = getattr(request.app.state, "session_clock", time.time)
    return SessionService(get_redis(request), clock)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


async def _close_in_own_transaction(
    db: AsyncSession,
    service: SessionService,
    session_id: str,
    record: SessionRecord,
    reason: RevokeReason,
    *,
    expired: str | None = None,
    request: HTTPConnection,
) -> None:
    """Закрыть сессию и записать аудит так, чтобы откат запроса (401) их не отменил."""
    try:
        maker = async_sessionmaker(bind=db.bind, expire_on_commit=False)
        async with transaction(maker) as own:
            await service.end(own, session_id, record.user_id, reason)
            if expired is not None:
                await audit.write(
                    own,
                    "auth.session.expired",
                    user_id=record.user_uuid,
                    ip=request.client.host if request.client else None,
                    session_id=session_id,
                    object_type="session",
                    object_id=id_hash(session_id).hex(),
                    details={"reason": expired},
                    actor="system",
                )
    except Exception:  # отказ во входе важнее записи: 401 отдаётся в любом случае
        log.exception("session_close_failed", reason=reason.value)


async def _load_user(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[User | None, frozenset[SystemRole]]:
    user = await db.get(User, user_id, populate_existing=True)
    if user is None:
        return None, frozenset()
    roles = (await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))).all()
    return user, frozenset(SystemRole(r) for r in roles)


async def _support_projects(
    db: AsyncSession, user_id: uuid.UUID, roles: frozenset[SystemRole]
) -> frozenset[uuid.UUID]:
    if SystemRole.ADMIN not in roles:
        return frozenset()
    rows = await db.scalars(
        select(SupportSession.project_id).where(
            SupportSession.admin_id == user_id,
            SupportSession.ended_at.is_(None),
            SupportSession.expires_at > datetime.now(UTC),
        )
    )
    return frozenset(rows.all())


async def resolve_principal(
    conn: HTTPConnection,
    db: AsyncSession,
    service: SessionService,
    session_id: str | None,
    *,
    touch: bool,
) -> Principal:
    """Пользователь сессии по актуальным данным БД; иначе :class:`UnauthenticatedError`.

    ``touch=False`` — проверка без продления сессии: подключение WebSocket и его периодическая
    перепроверка (RT-003, RT-008; heartbeat не продлевает сессию, FR-SESS-02).
    """
    if session_id is None:
        raise UnauthenticatedError
    loaded = await service.load(session_id)
    record = loaded.record
    if record is None:
        raise UnauthenticatedError
    if loaded.expired is not None:
        await _close_in_own_transaction(
            db, service, session_id, record, RevokeReason.EXPIRED,
            expired=loaded.expired.value, request=conn,
        )  # fmt: skip
        raise UnauthenticatedError(loaded.expired.value)

    user, roles = await _load_user(db, record.user_uuid)
    if user is None or user.status is not UserStatus.ACTIVE:
        await _close_in_own_transaction(
            db, service, session_id, record, RevokeReason.BLOCKED, request=conn
        )
        raise UnauthenticatedError("blocked")

    if touch:
        record = await service.touch(db, session_id, record, background=False)
    return Principal(
        user_id=user.id,
        login=user.login,
        full_name=user.full_name,
        roles=roles,
        session_id=session_id,
        session=record,
        mfa_passed=record.mfa_passed,
        step_up_until=(
            datetime.fromtimestamp(record.step_up_until, UTC) if record.step_up_until else None
        ),
        enrollment_required=record.enrollment_required,
        password_change_required=record.password_change_required,
        support_projects=await _support_projects(db, user.id, roles),
    )


async def current_principal(
    request: Request, db: DbSession, service: SessionServiceDep
) -> Principal:
    principal = await resolve_principal(
        request, db, service, session_id_from(request), touch=not is_background(request)
    )
    request.state.principal = principal
    return principal


#: Аннотация параметра эндпоинта: ``async def handler(principal: CurrentPrincipal)``.
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
