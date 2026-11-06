"""Суперадминистратор из консоли (AUTH-011; SPEC FR-SA-01, FR-2FA-03, Q-22, BR-ROLE-03, 18.2).

* ``create-superadmin`` — локальная учётка в статусе «ждёт пароль» и ссылка активации на
  60 минут (пароль в аргументах не принимается);
* ``issue-activation`` — новая ссылка активации, прежняя аннулируется;
* ``reset-superadmin`` — ссылка сброса пароля на 60 минут; TOTP и резервные коды удаляются
  сразу (при следующем входе подключение TOTP обязательно), все сессии завершаются.

Адрес ссылки — ``APP_BASE_URL`` (до мастера настройки адреса в БД нет). Запуск команды пишет в
аудит общий хук CLI (``system.cli.executed``), действия — события ``users.created``,
``auth.password.reset_issued``, ``auth.mfa.reset`` с ``actor = cli``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import tokens
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import AuthTokenKind, RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import BackupCode, User, UserRole
from estimator.security import audit

LINK_TTL = timedelta(minutes=60)
MAX_SUPERADMINS = 3  # BR-ROLE-03: активных 2–3
_LIVE = (UserStatus.ACTIVE, UserStatus.PENDING_PASSWORD)


class SuperadminError(Exception):
    """Команду выполнить нельзя; текст — для оператора."""


@dataclass(frozen=True)
class IssuedLink:
    login: str
    link: str
    expires_minutes: int = int(LINK_TTL.total_seconds() // 60)


async def _superadmin_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role == SystemRole.SUPERADMIN, User.status.in_(_LIVE))
        )
        or 0
    )


async def _superadmin(db: AsyncSession, login: str) -> User:
    user = await db.scalar(select(User).where(User.login == login.strip()))
    if user is None:
        raise SuperadminError(f"Пользователь «{login}» не найден")
    is_super = await db.scalar(
        select(UserRole.user_id).where(
            UserRole.user_id == user.id, UserRole.role == SystemRole.SUPERADMIN
        )
    )
    if is_super is None:
        raise SuperadminError(f"«{user.login}» — не суперадминистратор")
    if user.status not in _LIVE:
        raise SuperadminError(f"Учётная запись «{user.login}» в статусе {user.status.value}")
    return user


async def _link(db: AsyncSession, user: User, kind: AuthTokenKind, base_url: str) -> IssuedLink:
    token = await tokens.issue(db, user.id, kind, ttl=LINK_TTL)
    return IssuedLink(user.login, tokens.link(base_url, kind, token))


async def create_superadmin(
    db: AsyncSession, *, login: str, email: str, base_url: str, os_user: str
) -> IssuedLink:
    login = login.strip()
    if not login or not email.strip():
        raise SuperadminError("Нужны логин и email")
    if await db.scalar(select(User.id).where(User.login == login)) is not None:
        raise SuperadminError(f"Логин «{login}» занят")
    if await _superadmin_count(db) >= MAX_SUPERADMINS:
        raise SuperadminError(
            f"Активных суперадминистраторов уже {MAX_SUPERADMINS} — больше нельзя (BR-ROLE-03)"
        )
    user = User(
        login=login,
        email=email.strip(),
        full_name=login,
        source=UserSource.LOCAL,
        status=UserStatus.PENDING_PASSWORD,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role=SystemRole.SUPERADMIN, source=RoleSource.MANUAL))
    await db.flush()
    await audit.write(
        db, "users.created", login=user.login, object_type="user", object_id=user.id,
        details={"source": "cli", "roles": [SystemRole.SUPERADMIN.value]},
        actor="cli", os_user=os_user,
    )  # fmt: skip
    return await _link(db, user, AuthTokenKind.ACTIVATION, base_url)


async def issue_activation(
    db: AsyncSession, *, login: str, base_url: str, os_user: str
) -> IssuedLink:
    user = await _superadmin(db, login)
    if user.status is not UserStatus.PENDING_PASSWORD:
        raise SuperadminError(
            f"Пароль «{user.login}» уже установлен: для восстановления — reset-superadmin"
        )
    return await _link(db, user, AuthTokenKind.ACTIVATION, base_url)


async def reset_superadmin(
    db: AsyncSession, sessions: SessionService, *, login: str, base_url: str, os_user: str
) -> IssuedLink:
    user = await _superadmin(db, login)
    if user.status is not UserStatus.ACTIVE:
        raise SuperadminError(f"«{user.login}» ещё не активирован: используйте issue-activation")
    roles = [SystemRole.SUPERADMIN.value]
    issued = await _link(db, user, AuthTokenKind.PASSWORD_RESET, base_url)
    user.totp_enabled = False
    user.totp_secret_enc = None
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user.id))
    count = await sessions.revoke_user(db, user.id, RevokeReason.PASSWORD_CHANGED)
    common = {"login": user.login, "object_type": "user", "object_id": user.id,
              "actor": "cli", "os_user": os_user}  # fmt: skip
    await audit.write(db, "auth.password.reset_issued",
                      details={"target_roles": roles, "delivery": "cli"}, **common)  # fmt: skip
    await audit.write(db, "auth.mfa.reset", details={"target_roles": roles}, **common)
    if count:
        details = {"count": count, "reason": "password_reset"}
        await audit.write(db, "auth.sessions.terminated", details=details, **common)
    return issued
