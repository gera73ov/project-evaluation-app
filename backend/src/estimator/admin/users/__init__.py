"""Пользователи в админке администратора (ADM-006; SPEC 7.5 «Пользователи», FR-AUTH-LOC-01,
FR-AUTH-AD-07, FR-2FA-03, FR-SESS-05, BR-ROLE-08, BR-PRJ-07, SEC-AUTHZ-06; 15.2 ``/admin/users``).

* Список и карточка — все учётки, кроме суперадминистраторов и аудиторов ИБ: их ведёт
  суперадминистратор в разделе «Система» (FR-SA-05). Для администратора такие учётки — 404.
* Создание — режим «Приложение»: логин (латиница, цифры, ``.``, ``-``, ``_``, 3–64, уникален без
  учёта регистра), ФИО, email (уникален), роли «Модератор», «Пресейл», «Руководитель пресейла».
  Пароль не задаётся: статус «ждёт пароль» и ссылка активации на 72 часа — письмом, а без SMTP
  или email — в ответе для показа на экране. Режим AD: человек из поиска по каталогу
  (``ad_object_guid``, AUTH-017) — учётка AD до первого входа, без пароля и ссылки.
* Изменение — ФИО, email и роли. ``roles`` в запросе — полный набор ролей, которые выдаёт
  администратор; остальные роли учётки не трогаются. Правила — :mod:`role_rules` (SEC-017):
  свои роли не меняет никто, «Модератор» и «Пресейл» у пользователя AD при сопоставлении групп
  выдают группы. Снятие «Модератора» не исключает из проектов (BR-ROLE-08).
* Блокировка — статус ``blocked`` с причиной ``manual``: из проектов не исключает, уведомления не
  приходят (их получают только активные), сессии и WebSocket закрываются сразу (FR-SESS-05,
  RT-008); проекты, где это был последний активный модератор, получают ``no_moderator_since`` и
  уведомление администраторам (BR-PRJ-07). Разблокировка возвращает статус по паролю.
* Сброс пароля и TOTP — со step-up (право ``users.reset_credentials``).

Учётки администраторов (как и суперадминистраторов) администратор не блокирует, не правит и не
сбрасывает им пароль и TOTP — это делает суперадминистратор (FR-SA-05, FR-2FA-03); роли
«Модератор», «Пресейл», «Руководитель пресейла» другому администратору выдать можно.
Анонимизированная учётка для изменений — 404 (SEC-PD-03).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth import passwords, tokens
from estimator.auth.context import Principal
from estimator.auth.policy import load_auth_mode, read_settings
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import (
    AuthTokenKind,
    ProjectRole,
    RoleSource,
    SystemRole,
    UserBlockReason,
    UserSource,
    UserStatus,
)
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import BackupCode, User, UserRole
from estimator.security import audit
from estimator.security.authz import role_rules
from estimator.services.team import refresh_no_moderator

#: Учётки раздела «Система»: в админке администратора их нет (FR-SA-05)
HIDDEN = frozenset({SystemRole.SUPERADMIN, SystemRole.SECURITY_AUDITOR})
#: Учётки, которые администратор не блокирует, не правит и не сбрасывает (FR-SA-05, FR-2FA-03)
PRIVILEGED = frozenset({SystemRole.ADMIN, SystemRole.SUPERADMIN})


@dataclass(frozen=True)
class ListFilter:
    q: str | None = None
    status: UserStatus | None = None
    role: SystemRole | None = None


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def user_out(user: User, roles: Iterable[UserRole]) -> dict[str, Any]:
    """``User`` контракта."""
    return {
        "id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "email": user.email,
        "source": user.source.value,
        "system_roles": [
            {"role": r.role.value, "source": r.source.value}
            for r in sorted(roles, key=lambda r: r.role.value)
        ],
        "status": user.status.value,
        "block_reason": user.block_reason.value if user.block_reason else None,
        "last_login_at": _iso(user.last_login_at),
        "totp_enabled": user.totp_enabled,
    }


async def _roles(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[UserRole]]:
    out: dict[uuid.UUID, list[UserRole]] = {i: [] for i in ids}
    if ids:
        for row in await db.scalars(select(UserRole).where(UserRole.user_id.in_(ids))):
            out[row.user_id].append(row)
    return out


def _visible() -> Any:
    return ~exists().where(UserRole.user_id == User.id, UserRole.role.in_(tuple(HIDDEN)))


async def list_users(
    db: AsyncSession, filt: ListFilter, *, after: dict[str, Any] | None, limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Страница списка по ФИО и ``id``; вторым — позиция следующей страницы (или ``None``)."""
    stmt = select(User).where(_visible())
    if filt.q and filt.q.strip():
        pattern = _like(filt.q.strip())
        stmt = stmt.where(
            or_(
                User.login.ilike(pattern, escape="\\"),
                User.full_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if filt.status is not None:
        stmt = stmt.where(User.status == filt.status)
    if filt.role is not None:
        stmt = stmt.where(exists().where(UserRole.user_id == User.id, UserRole.role == filt.role))
    if after is not None:
        try:
            name, last = str(after["n"]), uuid.UUID(str(after["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("CURSOR_INVALID") from exc
        stmt = stmt.where(or_(User.full_name > name, (User.full_name == name) & (User.id > last)))
    rows = list(await db.scalars(stmt.order_by(User.full_name, User.id).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    roles = await _roles(db, [u.id for u in page])
    nxt = {"n": page[-1].full_name, "id": str(page[-1].id)} if more else None
    return [user_out(u, roles[u.id]) for u in page], nxt


async def _load(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> User:
    stmt = select(User).where(User.id == user_id, _visible())
    if lock:
        stmt = stmt.with_for_update()
    user = await db.scalar(stmt)
    if user is None:
        raise ApiError("NOT_FOUND")
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    user = await _load(db, user_id)
    return user_out(user, (await _roles(db, [user.id]))[user.id])


def _privileged_denied() -> ApiError:
    return ApiError(
        "FORBIDDEN",
        detail="Учётки администраторов ведёт суперадминистратор",
        permission="system.admins.manage",
    )


async def _is_privileged(db: AsyncSession, user_id: uuid.UUID) -> bool:
    role = await db.scalar(
        select(UserRole.role).where(UserRole.user_id == user_id, UserRole.role.in_(PRIVILEGED))
    )
    return role is not None


async def _manageable(
    db: AsyncSession, user_id: uuid.UUID, *, allow_privileged: bool = False
) -> User:
    """Учётка для изменения: не анонимизирована (иначе 404) и, если не ``allow_privileged``, не
    администратора (иначе 403)."""
    user = await _load(db, user_id, lock=True)
    if user.status == UserStatus.ANONYMIZED:
        raise ApiError("NOT_FOUND")
    if not allow_privileged and await _is_privileged(db, user.id):
        raise _privileged_denied()
    return user


async def _unique(
    db: AsyncSession, *, login: str | None, email: str | None, exclude: uuid.UUID | None
) -> None:
    for field, column, value in (("login", User.login, login), ("email", User.email, email)):
        if value is None:
            continue
        stmt = select(User.id).where(func.lower(column) == value.lower())
        if exclude is not None:
            stmt = stmt.where(User.id != exclude)
        if await db.scalar(stmt.limit(1)) is not None:
            raise ApiError("ALREADY_EXISTS", field=field)


def _validation(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


def _clean_email(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


@dataclass(frozen=True)
class Activation:
    url: str | None
    emailed: bool
    expires_at: dt.datetime

    def out(self) -> dict[str, Any]:
        return {
            "emailed": self.emailed,
            "activation_url": None if self.emailed else self.url,
            "expires_at": _iso(self.expires_at),
        }


def _expiry(kind: AuthTokenKind) -> dt.datetime:
    return dt.datetime.now(dt.UTC) + tokens.TTL[kind]


async def create_user(
    db: AsyncSession,
    actor: Principal,
    *,
    login: str,
    full_name: str,
    email: str | None,
    roles: Iterable[str],
    ad_object_guid: uuid.UUID | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Завести локального пользователя (FR-AUTH-LOC-01); вернуть ``User`` и ссылку активации."""
    mode = await load_auth_mode(db)
    if ad_object_guid is not None or mode != "local":
        if mode == "local":
            raise _validation("ad_object_guid", "Из каталога AD заводят только в режиме AD")
        if ad_object_guid is None:
            raise _validation("ad_object_guid", "Выберите человека из каталога AD")
        return await _create_from_ad(db, actor, ad_object_guid, roles)
    login, full_name, email = login.strip(), full_name.strip(), _clean_email(email)
    wanted = sorted({SystemRole(r) for r in roles})
    if not full_name:
        raise _validation("full_name", "Укажите ФИО")
    role_rules.check_change(
        actor_id=actor.user_id, actor_roles=actor.roles, target_id=uuid.uuid4(),
        before=(), after=wanted,
    )  # fmt: skip
    await _unique(db, login=login, email=email, exclude=None)
    user = User(
        login=login,
        full_name=full_name,
        email=email,
        source=UserSource.LOCAL,
        status=UserStatus.PENDING_PASSWORD,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(user)
    await db.flush()
    for role in wanted:
        db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    await db.flush()
    await audit.write(
        db, "users.created", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"source": "admin_local", "roles": [r.value for r in wanted]},
    )  # fmt: skip
    link = await passwords.issue_activation(db, user, created_by=actor.user_id)
    activation = Activation(link.link, link.emailed, _expiry(AuthTokenKind.ACTIVATION))
    return user_out(user, (await _roles(db, [user.id]))[user.id]), activation.out()


async def _create_from_ad(
    db: AsyncSession, actor: Principal, guid: uuid.UUID, roles: Iterable[str]
) -> tuple[dict[str, Any], None]:
    """Заведение из каталога AD до первого входа (AUTH-017, FR-AUTH-AD-10): без пароля и ссылки."""
    from estimator.auth import ad_search

    wanted = sorted({SystemRole(r) for r in roles})
    role_rules.check_change(
        actor_id=actor.user_id, actor_roles=actor.roles, target_id=uuid.uuid4(), before=(),
        after=wanted, ad_mapping_locked=await _ad_mapping_enabled(db),
    )  # fmt: skip
    user, created = await ad_search.ensure_user(
        db, actor, guid, source="admin_ad_search", roles=[r.value for r in wanted]
    )
    if not created:
        raise ApiError("ALREADY_EXISTS", detail="Этот человек уже заведён", field="ad_object_guid")
    for role in wanted:
        db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    await db.flush()
    return user_out(user, (await _roles(db, [user.id]))[user.id]), None


async def _ad_mapping_enabled(db: AsyncSession) -> bool:
    raw = (await read_settings(db, "auth.ad.role_mapping")).get("auth.ad.role_mapping")
    return isinstance(raw, dict) and bool(raw.get("enabled"))


async def patch_user(
    db: AsyncSession,
    actor: Principal,
    user_id: uuid.UUID,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Изменить ФИО, email и выдаваемые администратором роли (SEC-AUTHZ-06, FR-AUTH-AD-07)."""
    user = await _manageable(db, user_id, allow_privileged=True)
    current = (await _roles(db, [user.id]))[user.id]
    diff: dict[str, list[Any]] = {}
    if "full_name" in changes:
        name = str(changes["full_name"]).strip()
        if not name:
            raise _validation("full_name", "Укажите ФИО")
        if name != user.full_name:
            diff["full_name"] = [user.full_name, name]
    if "email" in changes:
        email = _clean_email(changes["email"])
        if (email or "").lower() != (user.email or "").lower():
            await _unique(db, login=None, email=email, exclude=user.id)
            diff["email"] = [user.email, email]
    if "roles" in changes:
        await _change_roles(db, actor, user, current, {SystemRole(r) for r in changes["roles"]})
    if diff and await _is_privileged(db, user.id):
        raise _privileged_denied()
    if diff:
        user.full_name = diff.get("full_name", [None, user.full_name])[1]
        if "email" in diff:
            user.email = diff["email"][1]
        user.updated_by = actor.user_id
        await db.flush()
        await audit.write(
            db, "users.updated", user_id=actor.user_id, login=actor.login,
            session_id=actor.session_id, object_type="user", object_id=user.id,
            details={"changes": diff},
        )  # fmt: skip
    return user_out(user, (await _roles(db, [user.id]))[user.id])


async def _change_roles(
    db: AsyncSession,
    actor: Principal,
    user: User,
    current: list[UserRole],
    requested: set[SystemRole],
) -> None:
    before = {r.role for r in current}
    after = (before - role_rules.ADMIN_GRANTS) | requested
    if after == before:
        return
    locked = user.source == UserSource.AD and await _ad_mapping_enabled(db)
    role_rules.check_change(
        actor_id=actor.user_id, actor_roles=actor.roles, target_id=user.id,
        before=before, after=after, ad_mapping_locked=locked,
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
    await audit.write(
        db, "users.roles.changed", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"added": [r.value for r in added], "removed": [r.value for r in removed],
                 "source": "manual"},
    )  # fmt: skip


async def _moderated_projects(db: AsyncSession, user_id: uuid.UUID) -> list[Project]:
    stmt = (
        select(Project)
        .where(
            exists().where(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user_id,
                ProjectMember.role == ProjectRole.MODERATOR,
            )
        )
        .order_by(Project.id)
        .with_for_update()
    )
    return list(await db.scalars(stmt))


async def block_user(
    db: AsyncSession, sessions: SessionService, actor: Principal, user_id: uuid.UUID
) -> dict[str, Any]:
    """Заблокировать (``manual``): сессии закрываются, проекты без модератора помечаются."""
    if user_id == actor.user_id:
        raise ApiError("FORBIDDEN", detail="Свою учётку заблокировать нельзя",
                       permission="users.manage")  # fmt: skip
    user = await _manageable(db, user_id)
    await block(db, sessions, actor, user)
    return user_out(user, (await _roles(db, [user.id]))[user.id])


async def block(db: AsyncSession, sessions: SessionService, actor: Principal, user: User) -> bool:
    """Блокировка учётки (без проверок, кто кого блокирует); ``False`` — уже заблокирована."""
    if user.status == UserStatus.BLOCKED:
        return False
    user.status = UserStatus.BLOCKED
    user.block_reason = UserBlockReason.MANUAL
    user.blocked_at = dt.datetime.now(dt.UTC)
    user.updated_by = actor.user_id
    await db.flush()
    await sessions.revoke_user(db, user.id, RevokeReason.BLOCKED)
    await audit.write(
        db, "users.blocked", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"block_reason": UserBlockReason.MANUAL.value},
    )  # fmt: skip
    for project in await _moderated_projects(db, user.id):
        await refresh_no_moderator(db, project)
    await db.flush()
    return True


async def unblock_user(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> dict[str, Any]:
    """Разблокировать: ``active``, а если пароль ещё не установлен — ``pending_password``."""
    user = await _manageable(db, user_id)
    await unblock(db, actor, user)
    return user_out(user, (await _roles(db, [user.id]))[user.id])


async def unblock(db: AsyncSession, actor: Principal, user: User) -> bool:
    """Разблокировка учётки (без проверок прав); ``False`` — не была заблокирована."""
    if user.status != UserStatus.BLOCKED:
        return False
    previous = user.block_reason
    has_password = user.source == UserSource.AD or user.password_hash is not None
    user.status = UserStatus.ACTIVE if has_password else UserStatus.PENDING_PASSWORD
    user.block_reason = None
    user.blocked_at = None
    user.updated_by = actor.user_id
    await db.flush()
    await audit.write(
        db, "users.unblocked", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"previous_reason": previous.value if previous else None, "automatic": False},
    )  # fmt: skip
    for project in await _moderated_projects(db, user.id):
        await refresh_no_moderator(db, project)
    await db.flush()
    return True


async def _target_roles(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return sorted(r.role.value for r in (await _roles(db, [user_id]))[user_id])


async def reset_password(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> dict[str, Any]:
    """Ссылка сброса пароля (60 минут); учётке, ещё не установившей пароль, — новая ссылка
    активации (72 часа). Письмом, а без SMTP или email — для показа на экране."""
    return await issue_reset(db, actor, await _manageable(db, user_id))


async def issue_reset(db: AsyncSession, actor: Principal, user: User) -> dict[str, Any]:
    """Ссылка сброса пароля или активации учётке ``user`` (без проверок, кто кому сбрасывает)."""
    from estimator.notifications.mail.recipients import Recipient
    from estimator.notifications.tasks import enqueue_email

    if user.source != UserSource.LOCAL:
        raise ApiError("FORBIDDEN", detail="Пароль пользователя AD задаёт каталог",
                       permission="users.reset_credentials")  # fmt: skip
    if user.status == UserStatus.PENDING_PASSWORD:
        link = await passwords.issue_activation(db, user, created_by=actor.user_id)
        activation = Activation(link.link, link.emailed, _expiry(AuthTokenKind.ACTIVATION))
    else:
        kind = AuthTokenKind.PASSWORD_RESET
        token = await tokens.issue(db, user.id, kind, created_by=actor.user_id)
        url = tokens.link(await passwords.base_url(db), kind, token)
        emailed = False
        if user.email and await passwords.smtp_configured(db):
            minutes = int(tokens.TTL[kind].total_seconds() // 60)
            emailed = enqueue_email(
                "password_reset", [Recipient(user.email, user.status.value)],
                {"link": url, "expires_minutes": minutes},
            ) > 0  # fmt: skip
        activation = Activation(url, emailed, _expiry(kind))
    await audit.write(
        db, "auth.password.reset_issued", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"target_roles": await _target_roles(db, user.id),
                 "delivery": "email" if activation.emailed else "screen"},
    )  # fmt: skip
    return activation.out()


async def reset_totp(
    db: AsyncSession, sessions: SessionService, actor: Principal, user_id: uuid.UUID
) -> None:
    """Сброс TOTP (FR-2FA-03): секрет и резервные коды удаляются, сессии завершаются — при
    следующем входе подключение заново, если его требует политика 2FA."""
    await clear_totp(db, sessions, actor, await _manageable(db, user_id))


async def clear_totp(
    db: AsyncSession, sessions: SessionService, actor: Principal, user: User
) -> None:
    """Удалить TOTP и резервные коды ``user``, завершить его сессии (без проверок прав)."""
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.updated_by = actor.user_id
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user.id))
    await db.flush()
    await sessions.revoke_user(db, user.id, RevokeReason.USER_REVOKED)
    await audit.write(
        db, "auth.mfa.reset", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"target_roles": await _target_roles(db, user.id)},
    )  # fmt: skip
