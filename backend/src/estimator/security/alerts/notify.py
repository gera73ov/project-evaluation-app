"""Письма оповещений ИБ (SEC-011; SEC-AUTH-07, Q-26, TC-AUTH-06).

Путь обычного оповещения: :func:`estimator.security.audit.write` записывает событие с ``alert``
→ после commit слушатель :func:`on_alert` ставит задачу ``estimator.security.alert`` → задача
(:func:`dispatch`) собирает адреса — все активные администраторы с почтой и
``security.alert_email`` — и ставит по письму ``security_alert`` на адрес через текущий SMTP.
Слушатель регистрирует :func:`install`: его вызывают приложение и worker при старте.

Смена SMTP (``system.settings.changed``, ``section = smtp``): код сохранения настроек вызывает
:func:`before_smtp_change` **до** применения — письма уходят через старый сервер; затем само
событие изменения отправляет их через новый. Если письмо через старый (или новый) сервер не
ушло окончательно, задача письма вызывает :func:`record_undelivered`: событие
``system.alert.delivery_failed`` в аудит (оттуда — в SIEM) и отметка для «Состояния системы»
(:func:`last_undelivered`). Изменение настроек при этом не отменяется.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.db.enums import SystemRole, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.logging import get_logger
from estimator.notifications.mail import Recipient

log = get_logger(__name__)

KIND = "security_alert"
ALERT_EMAIL = "security.alert_email"
UNDELIVERED_KEY = "alerts:undelivered"
UNDELIVERED_TTL = 30 * 24 * 3600
#: Каналы ``system.alert.delivery_failed.channel``
OLD_SMTP, NEW_SMTP = "old_smtp", "new_smtp"

_installed = False


def install() -> None:
    """Подписать :func:`on_alert` на события аудита с оповещением (один раз на процесс)."""
    global _installed
    if _installed:
        return
    from estimator.security import audit

    audit.add_alert_listener(on_alert)
    _installed = True


def on_alert(alert: Any) -> None:
    """Слушатель аудита: поставить задачу рассылки. Сбой очереди пишется в лог, не в ответ."""
    from estimator.security.alerts import rules

    key = rules.alert_key(alert.event_type, alert.details)
    channel = NEW_SMTP if key == "smtp_changed" else None
    enqueue(key, _now(), alert.login, alert.ip, channel)


def enqueue(
    key: str, time: str, actor_login: str | None, ip: str | None, channel: str | None
) -> None:
    """Поставить задачу ``estimator.security.alert`` (в тестах подменяется записью вызовов)."""
    from estimator.security.alerts.tasks import publish

    publish(key, time, actor_login, ip, channel)


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%d.%m.%Y %H:%M UTC")


async def recipients(conn: AsyncConnection | AsyncSession) -> list[Recipient]:
    """Активные администраторы с почтой и адрес службы ИБ из настроек (без повторов дальше)."""
    from estimator.auth.policy import read_settings

    rows = await conn.execute(
        select(User.email, User.status)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == SystemRole.ADMIN, User.status == UserStatus.ACTIVE)
        .order_by(User.login)
    )
    people = [Recipient(email, status.value) for email, status in rows.all()]
    alert_email = (await read_settings(conn, ALERT_EMAIL)).get(ALERT_EMAIL)
    if alert_email:
        people.insert(0, Recipient(str(alert_email), UserStatus.ACTIVE.value))
    return people


async def dispatch(
    conn: AsyncConnection | AsyncSession,
    key: str,
    *,
    time: str,
    actor_login: str | None,
    ip: str | None,
    channel: str | None = None,
    smtp_override: Mapping[str, Any] | None = None,
) -> int:
    """Поставить письма оповещения ``key``; вернуть их число."""
    from estimator.auth.passwords import base_url
    from estimator.notifications.tasks import enqueue_email

    fields = {"alert": key, "time": time, "actor_login": actor_login, "ip": ip,
              "link": f"{await base_url(conn)}/audit"}  # type: ignore[arg-type]  # fmt: skip
    people = await recipients(conn)
    sent = enqueue_email(KIND, people, fields, smtp_override=smtp_override, alert_channel=channel)
    if not sent:
        log.warning("security_alert_no_recipients", alert=key)
    return sent


async def before_smtp_change(
    conn: AsyncConnection | AsyncSession, *, actor_login: str | None, ip: str | None
) -> int:
    """До применения новых настроек SMTP: письма о смене через **старый** сервер (SEC-AUTH-07).

    Старые ``smtp.server`` и ``smtp.password`` (пароль в зашифрованном виде) уходят задаче
    письма. SMTP не был настроен — писать некуда, писем нет.
    """
    from estimator.notifications.mail.config import SmtpConfig, load_smtp_settings

    server, password = await load_smtp_settings(conn)  # type: ignore[arg-type]
    if not SmtpConfig.from_settings(server, None).configured:
        return 0
    return await dispatch(
        conn, "smtp_changed", time=_now(), actor_login=actor_login, ip=ip, channel=OLD_SMTP,
        smtp_override={"server": server, "password": password},
    )  # fmt: skip


async def record_undelivered(
    db: AsyncSession, redis: Redis | None, alert_type: str, channel: str
) -> None:
    """Оповещение не доставлено: событие в аудит (и SIEM) и отметка «Состояния системы»."""
    from estimator.security import audit

    await audit.write(
        db, "system.alert.delivery_failed", "failure", actor="system",
        object_type="setting", object_id="smtp.server",
        details={"alert_type": alert_type, "channel": channel},
    )  # fmt: skip
    if redis is None:
        return
    mark = {"alert_type": alert_type, "channel": channel, "at": dt.datetime.now(dt.UTC).isoformat()}
    try:
        await redis.set(UNDELIVERED_KEY, json.dumps(mark), ex=UNDELIVERED_TTL)
    except Exception:  # отметка не важнее записи в аудит
        log.exception("security_alert_undelivered_mark_failed")


async def last_undelivered(redis: Redis) -> dict[str, Any] | None:
    """Последнее недоставленное оповещение (за 30 дней) для «Состояния системы» (FR-SA-07)."""
    raw = await redis.get(UNDELIVERED_KEY)
    return json.loads(raw) if raw else None
