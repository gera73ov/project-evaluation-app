"""Профиль пользователя и его сессии (AUTH-010; SPEC 8.1, FR-SESS-04, FR-UI-02, FR-NOTIF-02).

* ФИО меняет только локальная учётка (у AD оно приходит из каталога) — иначе 403.
* Часовой пояс — имя IANA или ``null`` (часовой пояс приложения).
* TOTP по желанию: подключение в два шага (тот же поток, что принудительное, AUTH-007);
  отключение — право ``me.totp.disable`` (step-up) и только если TOTP не обязателен для ролей.
* Сессии: список живых, завершение одной (по непрозрачному хэшу) или всех, кроме текущей.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.auth.login import AuthError, user_roles
from estimator.auth.mfa_policy import ForbiddenError, load_mfa_policy
from estimator.auth.policy import load_auth_mode
from estimator.auth.providers import LOCAL
from estimator.auth.sessions import RevokeReason, SessionService, id_hash
from estimator.auth.totp import replace_backup_codes
from estimator.db.enums import UserSource
from estimator.db.models.users import BackupCode, User
from estimator.security import audit

TIMEZONE_MAX = 64


@dataclass(frozen=True)
class SessionView:
    id: str
    current: bool
    user_agent: str | None
    ip: str
    created_at: datetime
    last_seen_at: datetime


async def _user(db: AsyncSession, principal: Principal) -> User:
    user = await db.get(User, principal.user_id)
    if user is None:  # pragma: no cover — current_principal уже проверил учётку
        raise AuthError(401, "UNAUTHENTICATED")
    return user


def _ts(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


async def totp_required(db: AsyncSession, principal: Principal) -> bool:
    policy = await load_mfa_policy(db)
    return policy.required_for(await user_roles(db, principal.user_id))


async def me(db: AsyncSession, principal: Principal) -> dict[str, object]:
    """Тело ``GET /me`` (схема ``Me`` в contracts/openapi.yaml)."""
    user = await _user(db, principal)
    record = principal.session
    mode = await load_auth_mode(db)
    return {
        "id": str(user.id),
        "login": user.login,
        "full_name": user.full_name,
        "email": user.email,
        "source": str(user.source),
        "timezone": user.timezone,
        "system_roles": sorted(str(r) for r in principal.roles),
        "totp_enabled": user.totp_enabled,
        "totp_required": await totp_required(db, principal),
        "mfa_passed": principal.mfa_passed,
        "auth_mode": "app" if mode == LOCAL else "ad",
        "session_expires_at": _ts(record.absolute_at),
        "idle_timeout_seconds": record.idle_seconds,
    }


def _validation(field: str, code: str, message: str) -> AuthError:
    return AuthError(
        422, "VALIDATION_FAILED", errors=[{"field": field, "code": code, "message": message}]
    )


async def update_me(
    db: AsyncSession,
    principal: Principal,
    *,
    full_name: str | None,
    timezone: str | None,
    timezone_set: bool,
) -> None:
    user = await _user(db, principal)
    if full_name is not None:
        if user.source is not UserSource.LOCAL:
            raise ForbiddenError("FORBIDDEN")  # ФИО AD-пользователя приходит из каталога
        if not full_name.strip():
            raise _validation("/full_name", "required", "ФИО не может быть пустым")
        user.full_name = full_name.strip()
    if timezone_set:
        if timezone is not None and timezone not in zoneinfo.available_timezones():
            raise _validation("/timezone", "invalid", "Неизвестный часовой пояс")
        user.timezone = timezone
    await db.flush()


async def list_sessions(
    db: AsyncSession, sessions: SessionService, principal: Principal
) -> list[SessionView]:
    current = principal.session_hash
    return [
        SessionView(
            id=info.session_hash.hex(),
            current=info.session_hash == current,
            user_agent=info.user_agent,
            ip=info.record.ip,
            created_at=datetime.fromtimestamp(info.record.created_at, UTC),
            last_seen_at=datetime.fromtimestamp(info.record.last_seen_at, UTC),
        )
        for info in await sessions.list_user(db, principal.user_id)
    ]


async def end_sessions(
    db: AsyncSession, sessions: SessionService, principal: Principal, session_id: str | None
) -> bool:
    """Завершить одну сессию (по ``id`` из списка) или все, кроме текущей.

    Возвращает ``True``, если завершена текущая сессия (нужно снять cookie).
    """
    if session_id is None:
        count = await sessions.revoke_user(
            db, principal.user_id, RevokeReason.USER_REVOKED,
            except_session_id=principal.session_id,
        )  # fmt: skip
        ended_current = False
    else:
        try:
            hashed = bytes.fromhex(session_id)
        except ValueError:
            return False
        count = int(
            await sessions.end_by_hash(db, principal.user_id, hashed, RevokeReason.USER_REVOKED)
        )
        ended_current = count == 1 and hashed == id_hash(principal.session_id)
    if count:
        await audit.write(
            db, "auth.sessions.terminated", user_id=principal.user_id, login=principal.login,
            session_id=None if ended_current else principal.session_id,
            object_type="user", object_id=principal.user_id,
            details={"count": count, "reason": "self"},
        )  # fmt: skip
    return ended_current


async def disable_totp(db: AsyncSession, sessions: SessionService, principal: Principal) -> None:
    """Отключить свой TOTP: только если он не обязателен (FR-2FA-02, FR-2FA-04)."""
    user = await _user(db, principal)
    if await totp_required(db, principal):
        raise ForbiddenError("FORBIDDEN")
    if not user.totp_enabled:
        return
    user.totp_enabled = False
    user.totp_secret_enc = None
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user.id))
    await sessions.update(db, principal.session_id, principal.session, mfa_passed=False)
    await audit.write(
        db, "auth.mfa.disabled", user_id=user.id, login=user.login,
        session_id=principal.session_id, object_type="user", object_id=user.id, details={},
    )  # fmt: skip


async def regenerate_backup_codes(db: AsyncSession, principal: Principal) -> list[str]:
    user = await _user(db, principal)
    if not user.totp_enabled:
        raise ForbiddenError("TOTP_ENROLL_REQUIRED")
    codes = await replace_backup_codes(db, user.id)
    await audit.write(
        db, "auth.mfa.backup_codes_regenerated", user_id=user.id, login=user.login,
        session_id=principal.session_id, object_type="user", object_id=user.id, details={},
    )  # fmt: skip
    return codes


async def notification_settings(db: AsyncSession, principal: Principal) -> dict[str, bool]:
    user = await _user(db, principal)
    return {"notify_digest": user.notify_digest, "notify_questions": user.notify_questions}


async def set_notification_settings(
    db: AsyncSession, principal: Principal, *, notify_digest: bool, notify_questions: bool
) -> dict[str, bool]:
    user = await _user(db, principal)
    user.notify_digest = notify_digest
    user.notify_questions = notify_questions
    await db.flush()
    return {"notify_digest": notify_digest, "notify_questions": notify_questions}
