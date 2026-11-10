"""Вход в режиме «Приложение» (AUTH-004) и второй шаг TOTP (AUTH-006).

Шаг 1 — ``POST /auth/login`` (раздел 7.2, FR-AUTH-AD-13, FR-LOCK-01…05):

1. пустые поля → ``LOGIN_FAILED`` без проверки пароля;
2. логин суперадминистратора (без учёта регистра) проверяется только локально (FR-SA-03);
3. пока мастер настройки не завершён, входит только суперадминистратор (AUTH-012);
4. лимит попыток с IP и блокировка пары «логин + IP» (AUTH-005);
5. проверка пароля провайдером; любой отказ — один и тот же ``LOGIN_FAILED`` с сопоставимым
   временем (фиктивный хэш для неизвестных логинов); причина пишется только в аудит;
6. успех: TOTP подключён → ``{step: "totp", login_token}`` (временный токен 5 минут в Redis
   ``auth:pending:{sha256}``); TOTP обязателен, но не подключён → сессия до подключения
   (``step: "enroll"``, 15 минут); иначе — сессия (``step: "done"``). Если у локальной учётки
   истёк срок пароля (FR-AUTH-LOC-02, CR-003), сессия ограничена сменой пароля и выходом
   (``step: "password_change"``, 15 минут); это проверяется и после шага TOTP.

Шаг 2 — ``POST /auth/totp``: код TOTP или резервный код по временному токену. Неверный код —
неудачная попытка входа (FR-LOCK-03). Успех создаёт новую сессию с ``mfa_passed``.

Отказы пишутся в аудит отдельной транзакцией (:func:`audit.write_detached`): транзакция
запроса откатывается вместе с ответом-ошибкой.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import devices
from estimator.auth.lockout import Event, LockoutPolicy, LoginGuard
from estimator.auth.mfa_policy import load_mfa_policy
from estimator.auth.policy import load_auth_mode, load_session_policy, read_settings
from estimator.auth.providers import (
    LOCAL,
    Credentials,
    ProviderNotAvailableError,
    authenticate,
)
from estimator.auth.providers.base import is_local_superadmin
from estimator.auth.sessions import RevokeReason, SessionRecord, SessionService, id_hash
from estimator.auth.setup_gate import SetupInProgressError, setup_completed
from estimator.auth.totp import TotpVerifier, consume_backup_code, decrypt_secret
from estimator.db.enums import SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.logging import get_logger
from estimator.metrics import LOGIN_FAILURES
from estimator.security import audit
from estimator.security.audit import security_events
from estimator.security.crypto import get_cipher
from estimator.security.networks import guard_superadmin_login

log = get_logger(__name__)

PENDING_PREFIX = "auth:pending:"
PENDING_TTL = 300  # временный токен шага TOTP, 5 минут


class AuthError(HTTPException):
    """Ошибка входа с кодом из contracts/errors.yaml (тело RFC 9457 строит API-003)."""

    def __init__(
        self,
        status: int,
        code: str,
        *,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(status_code=status, detail={"code": code, **extensions}, headers=headers)
        self.code = code


def throttled(code: str, retry_after: int) -> AuthError:
    """429 ``RATE_LIMITED`` (лимит с IP) или ``LOGIN_LOCKED`` (блокировка пары) с Retry-After."""
    extra = {"retry_after": retry_after} if code == "RATE_LIMITED" else {}
    return AuthError(429, code, headers={"Retry-After": str(retry_after)}, **extra)


def login_failed(mode: str) -> AuthError:
    """Единый ответ на любой отказ по логину и паролю (FR-AUTH-AD-13)."""
    return AuthError(401, "LOGIN_FAILED", auth_mode="app" if mode == LOCAL else "ad")


@dataclass(frozen=True)
class LoginOutcome:
    step: str  # done | totp | enroll | password_change
    session_id: str | None = None
    record: SessionRecord | None = None
    login_token: str | None = None
    expires_in: int | None = None

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"step": self.step}
        if self.login_token is not None:
            out["login_token"] = self.login_token
        if self.expires_in is not None:
            out["expires_in"] = self.expires_in
        return out


@dataclass(frozen=True)
class Pending:
    """Содержимое ``auth:pending:{hash}``: кто прошёл пароль и ждёт второй шаг."""

    user_id: uuid.UUID
    login: str
    method: str
    superadmin: bool


def _token_key(token: str) -> str:
    return PENDING_PREFIX + hashlib.sha256(token.encode()).hexdigest()


async def load_lockout_policy(db: AsyncSession) -> LockoutPolicy:
    return LockoutPolicy.from_setting(
        (await read_settings(db, "security.lockout")).get("security.lockout")
    )


async def password_expired(db: AsyncSession, user: User) -> bool:
    """Срок пароля истёк (FR-AUTH-LOC-02): только локальная учётка, срок из политики паролей.

    Решение владельца 06.11.2026 (CR-003): вход с истёкшим паролем пускает только к смене пароля.
    У пользователей AD действует политика AD, срок приложения к ним не применяется.
    """
    from estimator.auth.passwords.policy import PasswordPolicy  # пакет passwords импортирует login

    if user.source is not UserSource.LOCAL or user.password_hash is None:
        return False
    values = await read_settings(db, "security.password_policy")
    policy = PasswordPolicy.from_setting(values.get("security.password_policy"))
    return policy.is_expired(user.password_changed_at)


async def user_roles(db: AsyncSession, user_id: uuid.UUID) -> list[SystemRole]:
    rows = await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))
    return [SystemRole(r) for r in rows.all()]


class LoginService:
    def __init__(self, redis: Redis, sessions: SessionService) -> None:
        self._redis = redis
        self.sessions = sessions

    # --- шаг 1: пароль ---

    async def password_step(
        self, db: AsyncSession, credentials: Credentials, *, ip: str, user_agent: str | None
    ) -> LoginOutcome:
        mode = await load_auth_mode(db)
        login = credentials.login.strip()
        if not login or not credentials.password:
            await self._failed(db, login or None, None, "empty_credentials", mode, ip, user_agent)
            raise login_failed(mode)

        superadmin = await is_local_superadmin(db, login)
        if superadmin:  # FR-SA-06: вход суперадминистратора только из разрешённых сетей
            await guard_superadmin_login(db, self._redis, ip=ip, login=login, route="/auth/login")
        if not superadmin and not await setup_completed(db):
            await self._failed(db, login, None, "setup_in_progress", mode, ip, user_agent)
            raise SetupInProgressError

        method_mode = LOCAL if superadmin else mode
        guard = LoginGuard(self._redis, await load_lockout_policy(db))
        gate = await guard.before_attempt(login, ip, superadmin=superadmin)
        if gate.code is not None:
            reason = "rate_limited" if gate.code == "RATE_LIMITED" else "locked_out"
            await self._failed(db, login, None, reason, method_mode, ip, user_agent)
            if gate.code == "RATE_LIMITED":  # SEC-010: 429 по IP — и в категорию «Безопасность»
                await security_events.rate_limited(
                    db, self._redis, "login_ip", ip, gate.retry_after or 1, login=login, ip=ip
                )
            raise throttled(gate.code, gate.retry_after)
        if gate.delay_seconds:
            await asyncio.sleep(gate.delay_seconds)

        try:
            result = await authenticate(db, method_mode, credentials)
        except ProviderNotAvailableError:
            raise AuthError(503, "AUTH_SERVICE_UNAVAILABLE") from None
        if result.reason == "ad_unavailable":  # FR-AUTH-AD-09: AD недоступен — не попытка входа
            await self._failed(db, login, result.user_id, "ad_unavailable", method_mode, ip,
                               user_agent)  # fmt: skip
            raise AuthError(503, "AUTH_SERVICE_UNAVAILABLE")
        if not result.ok or result.identity is None or result.identity.user_id is None:
            failure = await guard.record_failure(login, ip, superadmin=superadmin)
            await self._failed(
                db, login, result.user_id, result.reason or "user_not_found", method_mode, ip,
                user_agent,
                events=failure.events,
            )  # fmt: skip
            if failure.delay_seconds:
                await asyncio.sleep(failure.delay_seconds)
            raise login_failed(mode)

        user = await db.get(User, result.identity.user_id)
        if user is None:  # pragma: no cover — провайдер вернул удалённую учётку
            raise login_failed(mode)
        method = result.identity.provider
        if user.totp_enabled:
            token = secrets.token_urlsafe(32)
            pending = {"user_id": str(user.id), "login": user.login, "method": method,
                       "superadmin": superadmin}  # fmt: skip
            await self._redis.set(_token_key(token), json.dumps(pending), ex=PENDING_TTL)
            return LoginOutcome("totp", login_token=token, expires_in=PENDING_TTL)

        roles = await user_roles(db, user.id)
        enroll = (await load_mfa_policy(db)).required_for(roles)
        await guard.record_success(login, ip, superadmin=superadmin)
        expired = await password_expired(db, user)
        session_id, record = await self._open_session(
            db, user, roles, method, ip=ip, user_agent=user_agent, mfa=False, enroll=enroll,
            password_change=expired,
        )  # fmt: skip
        step = "password_change" if expired else "enroll" if enroll else "done"
        return LoginOutcome(step, session_id, record,
                            expires_in=record.expires_in(record.created_at))  # fmt: skip

    # --- шаг 2: TOTP или резервный код ---

    async def totp_step(
        self,
        db: AsyncSession,
        login_token: str,
        *,
        code: str | None,
        backup_code: str | None,
        ip: str,
        user_agent: str | None,
    ) -> LoginOutcome:
        pending = await self._pending(login_token)
        if pending is None:
            raise AuthError(401, "LOGIN_STEP_EXPIRED")
        if pending.superadmin:
            await guard_superadmin_login(
                db, self._redis, ip=ip, user_id=pending.user_id, login=pending.login,
                route="/auth/totp",
            )  # fmt: skip
        guard = LoginGuard(self._redis, await load_lockout_policy(db))
        gate = await guard.before_attempt(pending.login, ip, superadmin=pending.superadmin)
        if gate.code is not None:
            raise throttled(gate.code, gate.retry_after)
        if gate.delay_seconds:
            await asyncio.sleep(gate.delay_seconds)

        user = await db.get(User, pending.user_id)
        if user is None or user.status is not UserStatus.ACTIVE or not user.totp_enabled:
            await self._redis.delete(_token_key(login_token))
            raise AuthError(401, "LOGIN_STEP_EXPIRED")

        ok = False
        reason = "invalid_totp"
        if code is not None and user.totp_secret_enc is not None:
            secret = decrypt_secret(get_cipher(), user.id, user.totp_secret_enc)
            ok = await TotpVerifier(self._redis).verify(user.id, secret, code)
        elif backup_code is not None:
            reason = "invalid_backup_code"
            ok = await consume_backup_code(db, user.id, backup_code)
        if not ok:
            failure = await guard.record_failure(pending.login, ip, superadmin=pending.superadmin)
            await self._failed(
                db, pending.login, user.id, reason, pending.method, ip, user_agent,
                events=failure.events, step="totp",
            )  # fmt: skip
            if failure.delay_seconds:
                await asyncio.sleep(failure.delay_seconds)
            raise AuthError(401, "TOTP_INVALID")

        # токен одноразовый: второй параллельный запрос с тем же токеном получит «истёк»
        if not await self._redis.delete(_token_key(login_token)):
            raise AuthError(401, "LOGIN_STEP_EXPIRED")
        await guard.record_success(pending.login, ip, superadmin=pending.superadmin)
        roles = await user_roles(db, user.id)
        expired = await password_expired(db, user)
        session_id, record = await self._open_session(
            db, user, roles, pending.method, ip=ip, user_agent=user_agent, mfa=True, enroll=False,
            password_change=expired,
        )  # fmt: skip
        return LoginOutcome(
            "password_change" if expired else "done", session_id, record,
            expires_in=record.expires_in(record.created_at),
        )  # fmt: skip

    async def cancel(self, login_token: str) -> None:
        """«Назад» на экране кода: временный токен аннулируется."""
        await self._redis.delete(_token_key(login_token))

    async def logout(self, db: AsyncSession, session_id: str, user_id: uuid.UUID) -> None:
        await self.sessions.end(db, session_id, user_id, RevokeReason.LOGOUT)
        await audit.write(db, "auth.logout", user_id=user_id, session_id=session_id,
                          object_type="session", object_id=id_hash(session_id).hex())  # fmt: skip

    # --- внутреннее ---

    async def _pending(self, login_token: str) -> Pending | None:
        if not login_token or len(login_token) > 128:
            return None
        raw = await self._redis.get(_token_key(login_token))
        if raw is None:
            return None
        data = json.loads(raw)
        return Pending(uuid.UUID(data["user_id"]), data["login"], data["method"],
                       bool(data["superadmin"]))  # fmt: skip

    async def _open_session(
        self,
        db: AsyncSession,
        user: User,
        roles: list[SystemRole],
        method: str,
        *,
        ip: str,
        user_agent: str | None,
        mfa: bool,
        enroll: bool,
        password_change: bool = False,
    ) -> tuple[str, SessionRecord]:
        policy = await load_session_policy(db)
        session_id, record = await self.sessions.create(
            db, user.id, roles, policy, ip=ip, user_agent=user_agent,
            mfa_passed=mfa, enrollment_required=enroll, password_change_required=password_change,
        )  # fmt: skip
        user.last_login_at = datetime.now(UTC)
        new_device = await devices.on_login(
            db, user, roles, ip=ip, user_agent=user_agent, now=user.last_login_at
        )  # письмо о входе с нового устройства (AUTH-009)
        await audit.write(
            db,
            "auth.login.succeeded",
            user_id=user.id,
            login=user.login,
            ip=ip,
            user_agent=user_agent,
            session_id=session_id,
            object_type="session",
            object_id=id_hash(session_id).hex(),
            details={"method": method, "mfa": mfa, "new_device": new_device},
        )
        return session_id, record

    async def _failed(
        self,
        db: AsyncSession,
        login: str | None,
        user_id: uuid.UUID | None,
        reason: str,
        mode: str,
        ip: str,
        user_agent: str | None,
        *,
        events: tuple[Event, ...] = (),
        step: str = "password",
    ) -> None:
        method = "local" if mode == LOCAL else mode
        LOGIN_FAILURES.labels(method, step, reason).inc()  # SPEC 18.4 (INF-010)
        await audit.write_detached(
            db, "auth.login.failed", "failure", user_id=user_id, login=login, ip=ip,
            user_agent=user_agent, object_type="user", object_id=user_id,
            details={"reason": reason, "method": method, "step": step}, actor="anonymous",
        )  # fmt: skip
        for event in events:
            await audit.write_detached(
                db, event.type, "failure", user_id=user_id, login=login, ip=ip,
                object_type="user", object_id=user_id, details=event.details, actor="system",
            )  # fmt: skip
