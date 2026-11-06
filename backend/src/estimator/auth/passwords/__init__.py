"""Пароли режима «Приложение» (AUTH-008; FR-AUTH-LOC-01…04, SEC-AUTH-02, SEC-AUTH-03).

* :func:`activate` — установка пароля по ссылке активации (72 часа), ``pending_password`` →
  ``active``;
* :func:`request_reset` / :func:`reset` — «Забыли пароль»: ответ всегда одинаковый, ссылка
  60 минут, после сброса завершаются все сессии;
* :func:`change` — смена в профиле с текущим паролем, остальные сессии завершаются;
* :func:`issue_activation` — ссылка активации для администратора (письмо или показ на экране,
  если SMTP не настроен), используют ADM и консоль.

Каждая установка пароля проверяется политикой (:mod:`.policy`) и пишется в историю.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.login import AuthError
from estimator.auth.passwords.policy import PasswordPolicy, common_passwords
from estimator.auth.policy import read_settings
from estimator.auth.providers.local import hash_password_async, verify_password_async
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.auth.tokens import PAGES, TTL, consume, issue, link
from estimator.config import get_settings
from estimator.db.enums import AuthTokenKind, UserSource, UserStatus
from estimator.db.models.users import PasswordHistory, User
from estimator.logging import get_logger
from estimator.notifications.mail.config import SmtpConfig, load_smtp_settings
from estimator.notifications.mail.recipients import Recipient
from estimator.security import audit

log = get_logger(__name__)

__all__ = [
    "PAGES",
    "PasswordPolicy",
    "activate",
    "change",
    "common_passwords",
    "issue_activation",
    "request_reset",
    "reset",
]


async def load_password_policy(db: AsyncSession) -> PasswordPolicy:
    values = await read_settings(db, "security.password_policy")
    return PasswordPolicy.from_setting(values.get("security.password_policy"))


async def base_url(db: AsyncSession) -> str:
    """``app.base_url`` после мастера настройки, до него — ``APP_BASE_URL``."""
    value = (await read_settings(db, "app.base_url")).get("app.base_url")
    return str(value or get_settings().app_base_url).rstrip("/")


async def smtp_configured(db: AsyncSession) -> bool:
    server, _password = await load_smtp_settings(await db.connection())
    return SmtpConfig.from_settings(server, None).configured


async def _history(db: AsyncSession, user: User, keep: int) -> list[str]:
    if keep <= 0:
        return []
    rows = await db.scalars(
        select(PasswordHistory.password_hash)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(keep)
    )
    return list(rows.all())


async def set_password(
    db: AsyncSession, user: User, password: str, policy: PasswordPolicy | None = None
) -> None:
    """Проверить пароль политикой, сохранить хэш и историю. Нарушение — 422."""
    policy = policy or await load_password_policy(db)
    previous = await _history(db, user, policy.history)
    if user.password_hash and policy.history > 0:
        previous = [user.password_hash, *previous]
    found = await asyncio.to_thread(
        policy.violations,
        password,
        login=user.login,
        full_name=user.full_name,
        email=user.email,
        previous_hashes=previous,
    )
    if found:
        raise AuthError(422, "PASSWORD_POLICY_VIOLATION", violations=found)
    hashed = await hash_password_async(password)
    user.password_hash = hashed
    user.password_changed_at = datetime.now(UTC)
    db.add(PasswordHistory(user_id=user.id, password_hash=hashed))
    await db.flush()
    if policy.history > 0:
        keep = select(PasswordHistory.id).where(PasswordHistory.user_id == user.id)
        keep = keep.order_by(PasswordHistory.created_at.desc()).limit(policy.history)
        await db.execute(
            delete(PasswordHistory).where(
                PasswordHistory.user_id == user.id, PasswordHistory.id.not_in(keep)
            )
        )


def _token_invalid() -> AuthError:
    return AuthError(410, "TOKEN_INVALID")


async def activate(db: AsyncSession, token: str, password: str) -> User:
    """Установить пароль по ссылке активации (FR-AUTH-LOC-01, FR-SA-01)."""
    row = await consume(db, token, AuthTokenKind.ACTIVATION)
    user = await db.get(User, row.user_id) if row else None
    if user is None or user.source is not UserSource.LOCAL or user.status not in {
        UserStatus.PENDING_PASSWORD, UserStatus.ACTIVE,
    }:  # fmt: skip
        raise _token_invalid()
    await set_password(db, user, password)
    if user.status is UserStatus.PENDING_PASSWORD:
        user.status = UserStatus.ACTIVE
    await audit.write(
        db, "auth.password.set", user_id=user.id, login=user.login,
        object_type="user", object_id=user.id, details={"via": "activation"},
    )  # fmt: skip
    return user


async def request_reset(db: AsyncSession, login_or_email: str, *, ip: str | None) -> None:
    """«Забыли пароль» (FR-AUTH-LOC-03): ничего не сообщает о существовании учётки."""
    from estimator.notifications.tasks import enqueue_email

    value = login_or_email.strip()
    user = None
    if value:
        user = await db.scalar(
            select(User).where(
                or_(User.login == value, func.lower(User.email) == value.lower()),
                User.source == UserSource.LOCAL,
                User.status == UserStatus.ACTIVE,
            )
        )
    sent = False
    if user is not None and user.email and await smtp_configured(db):
        token = await issue(db, user.id, AuthTokenKind.PASSWORD_RESET)
        url = link(await base_url(db), AuthTokenKind.PASSWORD_RESET, token)
        minutes = int(TTL[AuthTokenKind.PASSWORD_RESET].total_seconds() // 60)
        sent = enqueue_email(
            "password_reset", [Recipient(user.email, user.status.value)],
            {"link": url, "expires_minutes": minutes},
        ) > 0  # fmt: skip
    await audit.write(
        db, "auth.password.reset_requested", user_id=user.id if user else None,
        login=value[:254] or None, ip=ip, object_type="user",
        object_id=user.id if user else None, details={"email_sent": sent}, actor="anonymous",
    )  # fmt: skip


async def reset(db: AsyncSession, sessions: SessionService, token: str, password: str) -> User:
    """Сброс по ссылке: новый пароль, все сессии пользователя завершаются."""
    row = await consume(db, token, AuthTokenKind.PASSWORD_RESET)
    user = await db.get(User, row.user_id) if row else None
    if user is None or user.source is not UserSource.LOCAL or user.status is not UserStatus.ACTIVE:
        raise _token_invalid()
    await set_password(db, user, password)
    count = await sessions.revoke_user(db, user.id, RevokeReason.PASSWORD_CHANGED)
    await audit.write(db, "auth.password.set", user_id=user.id, login=user.login,
                      object_type="user", object_id=user.id, details={"via": "reset"})  # fmt: skip
    await _audit_terminated(db, user, count, "password_reset")
    return user


async def change(
    db: AsyncSession,
    sessions: SessionService,
    user_id: uuid.UUID,
    current_session_id: str,
    current_password: str,
    new_password: str,
) -> int:
    """Смена в профиле (FR-AUTH-LOC-04). Возвращает число завершённых других сессий."""
    user = await db.get(User, user_id)
    if user is None or user.source is not UserSource.LOCAL or user.password_hash is None:
        raise AuthError(403, "FORBIDDEN")
    if not await verify_password_async(user.password_hash, current_password):
        raise AuthError(422, "CURRENT_PASSWORD_INVALID")
    await set_password(db, user, new_password)
    count = await sessions.revoke_user(
        db, user.id, RevokeReason.PASSWORD_CHANGED, except_session_id=current_session_id
    )
    await audit.write(
        db, "auth.password.changed", user_id=user.id, login=user.login,
        session_id=current_session_id, object_type="user", object_id=user.id,
    )  # fmt: skip
    await _audit_terminated(db, user, count, "password_changed")
    return count


@dataclass(frozen=True)
class ActivationLink:
    link: str
    emailed: bool


async def issue_activation(
    db: AsyncSession, user: User, *, created_by: uuid.UUID | None
) -> ActivationLink:
    """Ссылка установки пароля (72 часа): письмом, а без SMTP или email — для показа на экране."""
    from estimator.notifications.tasks import enqueue_email

    token = await issue(db, user.id, AuthTokenKind.ACTIVATION, created_by=created_by)
    url = link(await base_url(db), AuthTokenKind.ACTIVATION, token)
    emailed = False
    if user.email and await smtp_configured(db):
        hours = int(TTL[AuthTokenKind.ACTIVATION].total_seconds() // 3600)
        emailed = enqueue_email(
            "password_setup", [Recipient(user.email, user.status.value)],
            {"link": url, "expires_hours": hours},
        ) > 0  # fmt: skip
    return ActivationLink(url, emailed)


async def _audit_terminated(db: AsyncSession, user: User, count: int, reason: str) -> None:
    if count:
        await audit.write(db, "auth.sessions.terminated", user_id=user.id, login=user.login,
                          object_type="user", object_id=user.id,
                          details={"count": count, "reason": reason})  # fmt: skip
