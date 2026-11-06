"""Подключение TOTP в сессии и step-up (AUTH-006, AUTH-007).

Подключение (FR-2FA-04, ``/auth/totp/enroll*``): секрет создаётся при первом шаге и до
подтверждения живёт в Redis ``totp:enroll:{хэш сессии}`` в зашифрованном виде (15 минут).
Подтверждение первым кодом сохраняет секрет в ``users``, выдаёт 10 резервных кодов, отмечает
TOTP пройденным и меняет идентификатор сессии (FR-SESS-03); ограничение сессии до подключения
(15 минут) снимается — дальше действует обычный абсолютный срок.

Step-up (SEC-AUTH-05, FR-2FA-05, ``/auth/step-up``): пароль (в режиме AD — пароль AD) и код
TOTP открывают окно повторного подтверждения на 5 минут; вариант ``totp_only`` — только код,
для доступа к деньгам. Неудача — ``STEP_UP_FAILED``, сессия не завершается, попытка
учитывается блокировкой пары «логин + IP» (FR-LOCK-01, FR-LOCK-03).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.auth.lockout import LoginGuard
from estimator.auth.login import AuthError, load_lockout_policy, throttled
from estimator.auth.policy import (
    PRE_MFA_SECONDS,
    STEP_UP_SECONDS,
    load_auth_mode,
    load_session_policy,
)
from estimator.auth.providers import LOCAL, Credentials, ProviderNotAvailableError, authenticate
from estimator.auth.sessions import SessionRecord, SessionService, id_hash
from estimator.auth.totp import (
    TotpVerifier,
    decrypt_secret,
    encrypt_secret,
    new_secret,
    provisioning_uri,
    replace_backup_codes,
)
from estimator.db.models.users import User
from estimator.security import audit
from estimator.security.crypto import get_cipher

ENROLL_PREFIX = "totp:enroll:"


def _enroll_key(session_id: str) -> str:
    return ENROLL_PREFIX + id_hash(session_id).hex()


@dataclass(frozen=True)
class EnrollStart:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True)
class Rotated:
    """Новый идентификатор сессии после TOTP (cookie нужно переустановить)."""

    session_id: str
    record: SessionRecord
    backup_codes: tuple[str, ...] = ()


async def _user(db: AsyncSession, principal: Principal) -> User:
    user = await db.get(User, principal.user_id)
    if user is None:  # pragma: no cover — current_principal уже проверил учётку
        raise AuthError(401, "UNAUTHENTICATED")
    return user


async def start_enrollment(db: AsyncSession, redis: Redis, principal: Principal) -> EnrollStart:
    user = await _user(db, principal)
    if user.totp_enabled:
        raise AuthError(403, "FORBIDDEN")
    secret = new_secret()
    blob = encrypt_secret(get_cipher(), user.id, secret)
    await redis.set(_enroll_key(principal.session_id), base64.b64encode(blob), ex=PRE_MFA_SECONDS)
    return EnrollStart(secret, provisioning_uri(secret, user.login))


async def confirm_enrollment(
    db: AsyncSession,
    redis: Redis,
    sessions: SessionService,
    principal: Principal,
    code: str,
    *,
    user_agent: str | None,
) -> Rotated:
    user = await _user(db, principal)
    raw = await redis.get(_enroll_key(principal.session_id))
    if raw is None or user.totp_enabled:
        raise AuthError(401, "TOTP_INVALID")
    blob = base64.b64decode(raw)
    secret = decrypt_secret(get_cipher(), user.id, blob)
    if not await TotpVerifier(redis).verify(user.id, secret, code):
        raise AuthError(401, "TOTP_INVALID")
    await redis.delete(_enroll_key(principal.session_id))
    user.totp_secret_enc = blob
    user.totp_enabled = True
    codes = await replace_backup_codes(db, user.id)
    record = principal.session
    changes: dict[str, object] = {"mfa_passed": True, "enrollment_required": False}
    if record.enrollment_required:
        policy = await load_session_policy(db)
        changes["absolute_at"] = record.created_at + policy.absolute_seconds
    new_id, new_record = await sessions.rotate(
        db, principal.session_id, record, user_agent=user_agent, **changes
    )
    await audit.write(
        db,
        "auth.mfa.enrolled",
        user_id=user.id,
        login=user.login,
        session_id=new_id,
        object_type="user",
        object_id=user.id,
        details={"forced": record.enrollment_required},
    )
    return Rotated(new_id, new_record, tuple(codes))


async def step_up(
    db: AsyncSession,
    redis: Redis,
    sessions: SessionService,
    principal: Principal,
    *,
    code: str,
    password: str | None,
    totp_only: bool,
    ip: str,
    user_agent: str | None,
) -> Rotated:
    purpose = "money_totp" if totp_only else "step_up"
    user = await _user(db, principal)
    if not user.totp_enabled or user.totp_secret_enc is None:
        raise AuthError(403, "TOTP_ENROLL_REQUIRED")
    if not totp_only and not password:
        raise AuthError(
            422,
            "VALIDATION_FAILED",
            errors=[{"field": "/password", "code": "required", "message": "Нужен пароль"}],
        )
    superadmin = principal.is_superadmin
    guard = LoginGuard(redis, await load_lockout_policy(db))
    gate = await guard.before_attempt(user.login, ip, superadmin=superadmin)
    if gate.code is not None:
        raise throttled(gate.code, gate.retry_after)

    reason = None
    if not totp_only:
        mode = LOCAL if superadmin else await load_auth_mode(db)
        try:
            result = await authenticate(db, mode, Credentials(user.login, password or ""))
        except ProviderNotAvailableError:
            raise AuthError(503, "AUTH_SERVICE_UNAVAILABLE") from None
        if not result.ok or result.identity is None or result.identity.user_id != user.id:
            reason = "wrong_password"
    if reason is None:
        secret = decrypt_secret(get_cipher(), user.id, user.totp_secret_enc)
        if not await TotpVerifier(redis).verify(user.id, secret, code):
            reason = "invalid_totp"
    if reason is not None:
        failure = await guard.record_failure(user.login, ip, superadmin=superadmin)
        await audit.write_detached(
            db, "auth.step_up.failed", "failure", user_id=user.id, login=user.login, ip=ip,
            session_id=principal.session_id, object_type="session",
            object_id=principal.session_hash.hex(),
            details={"purpose": purpose, "reason": reason},
        )  # fmt: skip
        for event in failure.events:
            await audit.write_detached(
                db, event.type, "failure", user_id=user.id, login=user.login, ip=ip,
                object_type="user", object_id=user.id, details=event.details, actor="system",
            )  # fmt: skip
        raise AuthError(401, "STEP_UP_FAILED")

    await guard.record_success(user.login, ip, superadmin=superadmin)
    record = principal.session
    changes: dict[str, object] = {"mfa_passed": True}
    if not totp_only:
        changes["step_up_until"] = sessions.now() + STEP_UP_SECONDS
    new_id, new_record = await sessions.rotate(
        db, principal.session_id, record, user_agent=user_agent, **changes
    )
    await audit.write(
        db,
        "auth.step_up.passed",
        user_id=user.id,
        login=user.login,
        ip=ip,
        session_id=new_id,
        object_type="session",
        object_id=id_hash(new_id).hex(),
        details={"purpose": purpose},
    )
    return Rotated(new_id, new_record)
