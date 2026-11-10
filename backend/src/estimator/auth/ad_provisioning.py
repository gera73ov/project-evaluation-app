"""Учётные записи пользователей AD (AUTH-014; FR-AUTH-AD-06, Q-34, 14.2 ``ad_object_guid``).

Пользователь AD опознаётся по ``objectGUID``: переименование логина в AD не создаёт дубль. При
первом входе учётка создаётся с ролью «Пользователь» (без системных ролей, ``users.created``
``source = ad_jit``); при каждом входе логин, ФИО и email обновляются из AD (``users.updated``).
Анонимизированная учётка связь с AD теряет (SEC-014), поэтому тот же человек получает новую.

Блокировка по причинам AD (``ad_disabled``, ``ad_group``, ``ad_missing``) снимается при успешном
входе — проверки AD только что пройдены; ручная (``manual``) и «не сопоставлен при переходе»
(``not_matched``) — нет, вход отклоняется (``user_blocked``).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_roles
from estimator.auth.providers.ldap import AdConfig, Entry
from estimator.db.enums import UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import User
from estimator.logging import get_logger
from estimator.security import audit

log = get_logger(__name__)

AD_BLOCK_REASONS = frozenset(
    {UserBlockReason.AD_DISABLED, UserBlockReason.AD_GROUP, UserBlockReason.AD_MISSING}
)


class LoginTakenError(ValueError):
    """Логин из AD уже занят другой учётной записью приложения."""


async def by_guid(db: AsyncSession, guid: uuid.UUID) -> User | None:
    return await db.scalar(
        select(User).where(User.ad_object_guid == guid, User.status != UserStatus.ANONYMIZED)
    )


async def _taken(db: AsyncSession, column: Any, value: str | None, me: uuid.UUID | None) -> bool:
    if not value:
        return False
    query = select(User.id).where(func.lower(column) == value.lower())
    if me is not None:
        query = query.where(User.id != me)
    return await db.scalar(query.limit(1)) is not None


async def _email(db: AsyncSession, entry: Entry, me: uuid.UUID | None) -> str | None:
    if await _taken(db, User.email, entry.email, me):
        log.warning("ad_email_taken", object_guid=str(entry.object_guid))
        return None
    return entry.email


async def create(
    db: AsyncSession, entry: Entry, *, source: str, actor_id: uuid.UUID | None = None,
    actor_login: str | None = None, project_id: uuid.UUID | None = None,
    roles: Collection[str] = (),
) -> User:  # fmt: skip
    """Новая учётка AD (JIT или заведение заранее из поиска, AUTH-017)."""
    if await _taken(db, User.login, entry.login, None):
        raise LoginTakenError(entry.login)
    user = User(login=entry.login, full_name=entry.full_name[:200],
                email=await _email(db, entry, None), source=UserSource.AD,
                ad_object_guid=entry.object_guid, status=UserStatus.ACTIVE)  # fmt: skip
    db.add(user)
    await db.flush()
    details: dict[str, Any] = {"source": source, "roles": sorted(roles)}
    if project_id is not None:
        details["project_id"] = str(project_id)
    await audit.write(
        db, "users.created", user_id=actor_id, login=actor_login or user.login,
        object_type="user", object_id=user.id, details=details,
        actor="system" if actor_id is None else "user", project_id=project_id,
    )  # fmt: skip
    return user


async def refresh(db: AsyncSession, user: User, entry: Entry) -> dict[str, list[Any]]:
    """Обновить логин, ФИО и email из AD; вернуть изменения «было → стало»."""
    changes: dict[str, list[Any]] = {}
    if entry.login != user.login:
        if await _taken(db, User.login, entry.login, user.id):
            raise LoginTakenError(entry.login)
        changes["login"] = [user.login, entry.login]
        user.login = entry.login
    name = entry.full_name[:200]
    if name != user.full_name:
        changes["full_name"] = [user.full_name, name]
        user.full_name = name
    email = await _email(db, entry, user.id)
    if (email or "").lower() != (user.email or "").lower():
        changes["email"] = [user.email, email]
        user.email = email
    if changes:
        await db.flush()
        await audit.write(db, "users.updated", login=user.login, object_type="user",
                          object_id=user.id, details={"changes": changes},
                          actor="system")  # fmt: skip
    return changes


async def unblock_automatic(db: AsyncSession, user: User) -> None:
    previous = user.block_reason
    user.status = UserStatus.ACTIVE
    user.block_reason = None
    user.blocked_at = None
    await db.flush()
    await audit.write(
        db, "users.unblocked", login=user.login, object_type="user", object_id=user.id,
        details={"previous_reason": previous.value if previous else None, "automatic": True},
        actor="system",
    )  # fmt: skip


async def on_login(
    db: AsyncSession, config: AdConfig, entry: Entry, groups: Collection[str]
) -> tuple[User | None, str | None]:
    """Учётка для успешной проверки в AD; вторым — причина отказа, если вход нельзя пустить."""
    user = await by_guid(db, entry.object_guid)
    try:
        if user is None:
            user = await create(db, entry, source="ad_jit")
        else:
            await refresh(db, user, entry)
    except LoginTakenError:
        log.warning("ad_login_taken", object_guid=str(entry.object_guid))
        return user, "ad_ambiguous"
    if user.status is UserStatus.BLOCKED:
        if user.block_reason not in AD_BLOCK_REASONS:
            return user, "user_blocked"
        await unblock_automatic(db, user)
    elif user.status is UserStatus.PENDING_PASSWORD:  # заведён заранее без пароля (AUTH-017)
        user.status = UserStatus.ACTIVE
    if config.mapping_enabled:
        await ad_roles.apply(db, user, ad_roles.desired(config.mappings, groups))
    return user, None
