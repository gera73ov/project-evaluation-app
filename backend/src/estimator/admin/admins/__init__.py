"""Суперадминистраторы, администраторы и аудиторы ИБ (ADM-004; SPEC FR-SA-05, FR-2FA-03,
BR-ROLE-02, BR-ROLE-03, Q-07, Q-22, SEC-AUTH-05, SEC-AUTH-07; 15.2 ``/system/admins``,
``/system/users/{id}/reset-password``, ``/reset-totp``).

* Список — учётки с ролями «Суперадминистратор», «Администратор», «Аудитор ИБ» (без
  анонимизированных), по ФИО. В ``roles`` — только эти три роли.
* Создание — локальная учётка со статусом «ждёт пароль» и ссылкой активации (письмом или на экран).
  Суперадминистраторов 2–3: четвёртого создать нельзя (409 ``SUPERADMIN_LIMIT``). Суперадминистратор
  всегда входит локально (FR-SA-03). Заведение администратора из каталога AD — с поиском AD
  (AUTH-017): до него ``ad_object_guid`` или режим AD для не-суперадминистратора — 422.
* ``PATCH`` — ``roles``: полный набор ролей «Администратор» и «Аудитор ИБ» учётки (выдача и снятие,
  правила SEC-017: аудитор ИБ совместим только с «Пользователь», свои роли не меняет никто);
  ``status``: блокировка и разблокировка, последнего активного суперадминистратора блокировать
  нельзя (409 ``LAST_SUPERADMIN``).
* ``DELETE`` — разжалование: снимаются роли «Суперадминистратор», «Администратор», «Аудитор ИБ»;
  учётка остаётся «Пользователем». Сессии завершаются: права в них устарели.
* Сброс пароля и TOTP — администраторам, суперадминистраторам и аудиторам ИБ, кроме себя.

Каждое действие — со step-up (права ``system.admins.manage``, ``system.users.reset_credentials``),
событие ``system.privileged_account.changed`` (оповещение ИБ и администраторам — всегда) или
события сброса из ADM-006.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import users
from estimator.api.common.errors import ApiError
from estimator.auth import passwords
from estimator.auth.context import Principal
from estimator.auth.policy import load_auth_mode
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import (
    AuthTokenKind,
    RoleSource,
    SystemRole,
    UserSource,
    UserStatus,
)
from estimator.db.models.users import User, UserRole
from estimator.security import audit
from estimator.security.authz import role_rules

#: Роли раздела «Суперадминистраторы и администраторы», «Аудиторы ИБ»
SYSTEM_ROLES = (SystemRole.SUPERADMIN, SystemRole.ADMIN, SystemRole.SECURITY_AUDITOR)
LOGIN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


def account_out(user: User, roles: Iterable[UserRole]) -> dict[str, Any]:
    """``AdminAccount`` контракта."""
    return {
        "id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "email": user.email,
        "roles": sorted(r.role.value for r in roles if r.role in SYSTEM_ROLES),
        "status": user.status.value,
        "totp_enabled": user.totp_enabled,
        "last_login_at": users._iso(user.last_login_at),
    }


def _has_system_role() -> Any:
    return exists().where(UserRole.user_id == User.id, UserRole.role.in_(SYSTEM_ROLES))


async def list_admins(db: AsyncSession) -> list[dict[str, Any]]:
    stmt = (
        select(User)
        .where(_has_system_role(), User.status != UserStatus.ANONYMIZED)
        .order_by(User.full_name, User.id)
    )
    rows = list(await db.scalars(stmt))
    roles = await users._roles(db, [u.id for u in rows])
    return [account_out(u, roles[u.id]) for u in rows]


async def _account(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> User:
    """Учётка для изменения: есть и не анонимизирована (иначе 404), не своя (иначе 403)."""
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status == UserStatus.ANONYMIZED:
        raise ApiError("NOT_FOUND")
    if user.id == actor.user_id:
        raise ApiError("FORBIDDEN", detail="Свою учётку здесь менять нельзя",
                       permission="system.admins.manage")  # fmt: skip
    return user


async def _role_set(db: AsyncSession, user_id: uuid.UUID) -> set[SystemRole]:
    return {r.role for r in (await users._roles(db, [user_id]))[user_id]}


async def _privileged_event(
    db: AsyncSession, actor: Principal, user: User, role: SystemRole, op: str
) -> None:
    await audit.write(
        db, "system.privileged_account.changed", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"role": role.value, "op": op},
    )  # fmt: skip


def _top_role(roles: set[SystemRole]) -> SystemRole | None:
    return next((r for r in SYSTEM_ROLES if r in roles), None)


async def create_admin(
    db: AsyncSession,
    actor: Principal,
    *,
    login: str,
    email: str,
    full_name: str,
    role: str,
    ad_object_guid: uuid.UUID | None = None,
) -> dict[str, Any]:
    wanted = SystemRole(role)
    login, full_name = login.strip(), full_name.strip()
    email_clean = users._clean_email(email)
    if not LOGIN.match(login):
        raise users._validation("login", "Логин: латиница, цифры, «.», «-», «_», 3–64 символа")
    if not full_name:
        raise users._validation("full_name", "Укажите ФИО")
    if ad_object_guid is not None or (
        wanted != SystemRole.SUPERADMIN and await load_auth_mode(db) != "local"
    ):
        # FR-SA-05: администратор из AD — поиском по каталогу (AUTH-017)
        raise users._validation("ad_object_guid", "Заведение из каталога AD пока недоступно")
    if wanted == SystemRole.SUPERADMIN:
        await role_rules.ensure_superadmin_slot(db)
    await users._unique(db, login=login, email=email_clean, exclude=None)
    user = User(
        login=login,
        full_name=full_name,
        email=email_clean,
        source=UserSource.LOCAL,
        status=UserStatus.PENDING_PASSWORD,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role=wanted, source=RoleSource.MANUAL))
    await db.flush()
    await audit.write(
        db, "users.created", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"source": "admin_local", "roles": [wanted.value]},
    )  # fmt: skip
    await _privileged_event(db, actor, user, wanted, "created")
    link = await passwords.issue_activation(db, user, created_by=actor.user_id)
    expires = users._expiry(AuthTokenKind.ACTIVATION)
    return users.Activation(link.link, link.emailed, expires).out()


async def _set_roles(
    db: AsyncSession, actor: Principal, user: User, requested: set[SystemRole]
) -> bool:
    before = await _role_set(db, user.id)
    if SystemRole.SUPERADMIN in requested ^ (before & {SystemRole.SUPERADMIN}):
        # роль выдаётся только созданием учётки и снимается разжалованием (FR-SA-05)
        raise ApiError("FORBIDDEN", permission="system.admins.manage")
    after = (before - role_rules.SUPERADMIN_GRANTS) | (requested - {SystemRole.SUPERADMIN})
    if after == before:
        return False
    role_rules.check_change(
        actor_id=actor.user_id, actor_roles=actor.roles, target_id=user.id,
        before=before, after=after,
    )  # fmt: skip
    added, removed = sorted(after - before), sorted(before - after)
    if removed:
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user.id, UserRole.role.in_(removed))
        )
    for role in added:
        db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    user.updated_by = actor.user_id
    await db.flush()
    for role in added:
        await _privileged_event(db, actor, user, role, "granted")
    for role in removed:
        await _privileged_event(db, actor, user, role, "revoked")
    return True


async def patch_admin(
    db: AsyncSession,
    sessions: SessionService,
    actor: Principal,
    user_id: uuid.UUID,
    changes: dict[str, Any],
) -> dict[str, Any]:
    user = await _account(db, actor, user_id)
    roles_changed = False
    if "roles" in changes:
        roles_changed = await _set_roles(db, actor, user, {SystemRole(r) for r in changes["roles"]})
    status = changes.get("status")
    current = await _role_set(db, user.id)
    top = _top_role(current)
    if status == "blocked":
        await role_rules.ensure_not_last_superadmin(db, user.id)
        if await users.block(db, sessions, actor, user) and top is not None:
            await _privileged_event(db, actor, user, top, "blocked")
    elif status == "active" and user.status == UserStatus.BLOCKED:
        if top == SystemRole.SUPERADMIN:
            await role_rules.ensure_superadmin_slot(db)  # заблокированные в предел не входят
        if await users.unblock(db, actor, user) and top is not None:
            await _privileged_event(db, actor, user, top, "unblocked")
    if roles_changed:
        await sessions.revoke_user(db, user.id, RevokeReason.USER_REVOKED)
    return account_out(user, (await users._roles(db, [user.id]))[user.id])


async def demote_admin(
    db: AsyncSession, sessions: SessionService, actor: Principal, user_id: uuid.UUID
) -> None:
    """Разжалование: снять системные роли раздела, учётка остаётся «Пользователем»."""
    user = await _account(db, actor, user_id)
    held = sorted(await _role_set(db, user.id) & set(SYSTEM_ROLES))
    if not held:
        raise ApiError("NOT_FOUND")
    if SystemRole.SUPERADMIN in held:
        await role_rules.ensure_not_last_superadmin(db, user.id)
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id, UserRole.role.in_(held)))
    user.updated_by = actor.user_id
    await db.flush()
    for role in held:
        await _privileged_event(db, actor, user, role, "revoked")
    await sessions.revoke_user(db, user.id, RevokeReason.USER_REVOKED)


async def _reset_target(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> User:
    user = await _account(db, actor, user_id)
    if not await _role_set(db, user.id) & set(SYSTEM_ROLES):
        # пароли и TOTP остальных сбрасывает администратор (ADM-006)
        raise ApiError("NOT_FOUND")
    return user


async def reset_password(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> dict[str, Any]:
    user = await _reset_target(db, actor, user_id)
    if user.source != UserSource.LOCAL:
        raise ApiError("FORBIDDEN", detail="Пароль пользователя AD задаёт каталог",
                       permission="system.users.reset_credentials")  # fmt: skip
    return await users.issue_reset(db, actor, user)


async def reset_totp(
    db: AsyncSession, sessions: SessionService, actor: Principal, user_id: uuid.UUID
) -> None:
    await users.clear_totp(db, sessions, actor, await _reset_target(db, actor, user_id))
