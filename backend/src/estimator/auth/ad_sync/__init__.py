"""Отзыв доступа и синхронизация с AD (AUTH-016; FR-AUTH-AD-08, Q-18, D-21, 14.2
``users.block_reason``, TC-AUTH-02, G-26).

* Каждые 15 минут (``sessions_15min``) — пользователи AD с активными сессиями; ежедневно в 03:00
  (``daily``) — все пользователи AD, плюс обновление ФИО и email и пересчёт ролей по группам.
* Для каждого: запись по ``objectGUID`` есть? не отключена (ACCOUNTDISABLE)? в группе доступа?
  Нет — блокировка с причиной ``ad_missing`` / ``ad_disabled`` / ``ad_group``, все сессии
  завершаются (WebSocket закрывается по событию завершения сессии, RT-008). Блокировка по причине
  AD снимается автоматически, когда причина ушла; ручная (``manual``) и ``not_matched`` — никогда.
* AD недоступен — проверка пропускается целиком: никого не блокируем, сессии не трогаем;
  «Состояние системы» показывает предупреждение (:func:`last_state`).
* Итог — ``users.ad_sync.completed`` в аудит, время и результат последней проверки — в Redis и
  в метрике ``estimator_ad_sync_last_run_timestamp_seconds``.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_provisioning, ad_roles
from estimator.auth.providers import ldap
from estimator.auth.providers.ldap import AdConfig, AdConfigError, AdUnavailableError, Directory
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import User, UserSession
from estimator.logging import get_logger
from estimator.metrics import gauge
from estimator.security import audit

log = get_logger(__name__)

SESSIONS = "sessions_15min"
DAILY = "daily"
STATE_KEY = "ad_sync:last"
LAST_RUN = gauge(
    "estimator_ad_sync_last_run_timestamp_seconds",
    "Время последней проверки пользователей в AD (AUTH-016)",
    ("kind", "result"),
)
#: Проверяемые статусы: анонимизированные с AD не связаны, «ждёт пароль» у AD не бывает.
CHECKED = (UserStatus.ACTIVE, UserStatus.BLOCKED, UserStatus.PENDING_PASSWORD)


@dataclass
class Summary:
    kind: str
    checked: int = 0
    blocked: int = 0
    unblocked: int = 0
    roles_changed: int = 0
    skipped_ad_unavailable: bool = False

    def details(self) -> dict[str, Any]:
        return {"kind": self.kind, "checked": self.checked, "blocked": self.blocked,
                "unblocked": self.unblocked, "roles_changed": self.roles_changed,
                "skipped_ad_unavailable": self.skipped_ad_unavailable}  # fmt: skip


async def _users(db: AsyncSession, kind: str) -> list[User]:
    query = select(User).where(User.source == UserSource.AD, User.ad_object_guid.is_not(None),
                               User.status.in_(CHECKED))  # fmt: skip
    if kind == SESSIONS:
        query = query.where(exists().where(UserSession.user_id == User.id,
                                           UserSession.revoked_at.is_(None)))  # fmt: skip
    return list((await db.scalars(query.order_by(User.login))).all())


async def _block(db: AsyncSession, sessions: SessionService, user: User,
                 reason: UserBlockReason) -> None:  # fmt: skip
    from estimator.admin.users import _moderated_projects
    from estimator.services.team import refresh_no_moderator

    user.status = UserStatus.BLOCKED
    user.block_reason = reason
    user.blocked_at = dt.datetime.now(dt.UTC)
    await db.flush()
    await sessions.revoke_user(db, user.id, RevokeReason.AD_CHECK)
    await audit.write(db, "users.blocked", login=user.login, object_type="user",
                      object_id=user.id, details={"block_reason": reason.value},
                      actor="system")  # fmt: skip
    for project in await _moderated_projects(db, user.id):
        await refresh_no_moderator(db, project)


async def _check(db: AsyncSession, sessions: SessionService, config: AdConfig,
                 directory: Directory, user: User, summary: Summary) -> None:  # fmt: skip
    if user.ad_object_guid is None:  # отобрано _users, проверка для типов
        return
    entry = await directory.by_guid(user.ad_object_guid)
    groups: set[str] = set()
    if entry is None:
        reason: UserBlockReason | None = UserBlockReason.AD_MISSING
    else:
        groups = await directory.groups_of(entry.dn, config.groups_to_check())
        reason = (UserBlockReason.AD_DISABLED if entry.disabled
                  else None if groups & set(config.access_groups)
                  else UserBlockReason.AD_GROUP)  # fmt: skip
    summary.checked += 1
    blocked_by_ad = user.status is UserStatus.BLOCKED and user.block_reason in (
        ad_provisioning.AD_BLOCK_REASONS
    )
    if reason is not None:
        if user.status is not UserStatus.BLOCKED:
            await _block(db, sessions, user, reason)
            summary.blocked += 1
        elif blocked_by_ad and user.block_reason is not reason:
            user.block_reason = reason  # причина AD сменилась — блокировка остаётся
        return
    if blocked_by_ad:
        await ad_provisioning.unblock_automatic(db, user)
        summary.unblocked += 1
    if summary.kind == DAILY and entry is not None:
        try:
            await ad_provisioning.refresh(db, user, entry)
        except ad_provisioning.LoginTakenError:
            log.warning("ad_sync_login_taken", user_id=str(user.id))
        if config.mapping_enabled:
            change = await ad_roles.apply(db, user, ad_roles.desired(config.mappings, groups))
            summary.roles_changed += not change.empty


async def run(db: AsyncSession, redis: Redis, kind: str,
              now: dt.datetime | None = None) -> Summary:  # fmt: skip
    """Одна проверка ``kind`` (``sessions_15min`` или ``daily``); в режиме «Приложение» — ничего."""
    from estimator.auth.policy import load_auth_mode

    summary = Summary(kind)
    if await load_auth_mode(db) != "ad":
        return summary
    now = now or dt.datetime.now(dt.UTC)
    sessions = SessionService(redis)
    try:
        config = await ldap.load_config(db)
        directory = ldap.directory(config)
        users = await _users(db, kind)
        async with db.begin_nested():  # AD отвалился на середине — ничего из этой проверки
            for user in users:
                await _check(db, sessions, config, directory, user, summary)
    except (AdConfigError, AdUnavailableError) as exc:
        log.warning("ad_sync_skipped", kind=kind, error=type(exc).__name__)
        summary = Summary(kind, skipped_ad_unavailable=True)
    await audit.write(db, "users.ad_sync.completed", actor="system", details=summary.details())
    result = "skipped" if summary.skipped_ad_unavailable else "ok"
    LAST_RUN.labels(kind, result).set(now.timestamp())
    await redis.set(f"{STATE_KEY}:{kind}", json.dumps(
        {"at": now.isoformat(), "ok": not summary.skipped_ad_unavailable, **summary.details()}
    ))  # fmt: skip
    log.info("ad_sync_completed", **summary.details())
    return summary


async def last_state(redis: Redis) -> dict[str, dict[str, Any]]:
    """Итоги последних проверок по видам (для «Состояния системы»)."""
    out: dict[str, dict[str, Any]] = {}
    for kind in (SESSIONS, DAILY):
        raw = await redis.get(f"{STATE_KEY}:{kind}")
        if raw:
            out[kind] = json.loads(raw)
    return out
