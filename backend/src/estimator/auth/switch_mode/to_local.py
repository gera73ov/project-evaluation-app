"""Переход «AD → Приложение» (AUTH-019; FR-AUTH-SW-01, таблица «AD → Приложение», 18.2) — только
консольной командой ``estimator auth-mode local`` (:mod:`estimator.cli.auth_mode`).

* Все пользователи AD становятся локальными без пароля (``source = local``, ``ad_object_guid``
  снимается); назначения, роли и TOTP сохраняются.
* Каждому незаблокированному — ссылка установки пароля (72 часа, статус «ждёт пароль»): письмом,
  если SMTP настроен и у пользователя есть email, иначе — строкой CSV «логин; ФИО; одноразовая
  ссылка» для выдачи администратором (FR-AUTH-LOC-01). Письма уходят после commit, чтобы при
  откате не разослать недействительные ссылки. Заблокированные остаются заблокированными с прежней
  причиной: ссылка им не выдаётся (администратор разблокирует и выдаст её сам).
* Сопоставление групп AD с ролями выключается, роли из групп становятся ручными.
* Все сессии, кроме сессий суперадминистраторов (их учётки всегда локальные и не меняются),
  завершаются; ``auth.mode = local``.
* Отчёт — ``system.auth_mode.switched`` (``via = cli``, с именем пользователя ОС); применение
  оповещает ИБ и администраторов (SEC-011). ``dry_run`` ничего не меняет, только считает.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_roles
from estimator.auth.providers import ldap
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import AuthTokenKind, SystemRole, UserSource, UserStatus
from estimator.db.models.settings import SystemSetting
from estimator.db.models.users import User, UserRole, UserSession
from estimator.security import audit


class SwitchRefused(Exception):
    """Переход невозможен (например, вход уже локальный)."""


@dataclass(frozen=True)
class Handout:
    """Строка CSV: ссылку администратор выдаёт сам."""

    login: str
    full_name: str
    link: str


@dataclass
class LocalResult:
    converted: int = 0
    emailed: int = 0
    blocked: list[str] = field(default_factory=list)
    handouts: list[Handout] = field(default_factory=list)
    roles_made_manual: int = 0
    sessions_ended: int = 0
    smtp: bool = False
    dry_run: bool = False


async def _ad_users(db: AsyncSession) -> list[User]:
    return list((await db.scalars(
        select(User).where(User.source == UserSource.AD, User.status != UserStatus.ANONYMIZED)
        .order_by(User.login)
    )).all())  # fmt: skip


async def _end_sessions(db: AsyncSession, sessions: SessionService) -> int:
    superadmin = exists().where(UserRole.user_id == UserSession.user_id,
                                UserRole.role == SystemRole.SUPERADMIN)  # fmt: skip
    users = (await db.scalars(
        select(UserSession.user_id).where(UserSession.revoked_at.is_(None), ~superadmin)
        .distinct()
    )).all()  # fmt: skip
    ended = 0
    for user_id in users:
        ended += await sessions.revoke_user(db, user_id, RevokeReason.MODE_SWITCH)
    return ended


async def to_local(
    db: AsyncSession, redis: Redis, *, os_user: str, dry_run: bool = False
) -> LocalResult:
    from estimator.auth.passwords import base_url, smtp_configured
    from estimator.auth.policy import load_auth_mode, read_settings
    from estimator.auth.tokens import TTL, issue, link
    from estimator.db.session import after_commit
    from estimator.notifications.mail.recipients import Recipient
    from estimator.notifications.tasks import enqueue_email

    if await load_auth_mode(db) != "ad":
        raise SwitchRefused("вход уже идёт через приложение")
    users = await _ad_users(db)
    result = LocalResult(smtp=await smtp_configured(db), dry_run=dry_run)
    result.converted = len(users)
    result.blocked = [u.login for u in users if u.status is UserStatus.BLOCKED]
    if dry_run:
        result.emailed = sum(
            1 for u in users if u.status is not UserStatus.BLOCKED and u.email and result.smtp
        )
        await _audit(db, result, os_user)
        return result
    root = await base_url(db)
    hours = int(TTL[AuthTokenKind.ACTIVATION].total_seconds() // 3600)
    letters: list[tuple[str, str]] = []
    for user in users:
        user.source = UserSource.LOCAL
        user.ad_object_guid = None
        user.password_hash = None
        user.password_changed_at = None
        if user.status is UserStatus.BLOCKED:
            continue
        user.status = UserStatus.PENDING_PASSWORD
        url = link(root, AuthTokenKind.ACTIVATION,
                   await issue(db, user.id, AuthTokenKind.ACTIVATION))  # fmt: skip
        if user.email and result.smtp:
            letters.append((user.email, url))
        else:
            result.handouts.append(Handout(user.login, user.full_name, url))
    await db.flush()
    result.emailed = len(letters)
    result.roles_made_manual = await ad_roles.make_manual(db)
    mapping = (await read_settings(db, ldap.ROLE_MAPPING)).get(ldap.ROLE_MAPPING) or {}
    await db.merge(SystemSetting(key=ldap.ROLE_MAPPING, value={**mapping, "enabled": False}))
    await db.merge(SystemSetting(key="auth.mode", value="local"))
    await db.flush()
    result.sessions_ended = await _end_sessions(db, SessionService(redis))
    await _audit(db, result, os_user)

    def send() -> None:
        for address, url in letters:
            enqueue_email("password_setup", [Recipient(address, UserStatus.PENDING_PASSWORD.value)],
                          {"link": url, "expires_hours": hours})  # fmt: skip

    after_commit(db, send)
    return result


async def _audit(db: AsyncSession, result: LocalResult, os_user: str) -> None:
    await audit.write(
        db, "system.auth_mode.switched", object_type="setting", object_id="auth.mode",
        details={"from": "ad", "to": "local", "via": "cli", "matched": result.converted,
                 "ambiguous_confirmed": 0, "ambiguous_rejected": 0, "not_found_blocked": 0,
                 "dry_run": result.dry_run},
        actor="cli", os_user=os_user,
    )  # fmt: skip
