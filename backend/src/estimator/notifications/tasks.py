"""Задачи Celery уведомлений (NTF-002).

``send_email`` отправляет одно письмо одному адресу с повторами при временных сбоях SMTP
(сеть, таймаут, ответ 4xx): 30 с, 1, 2, 4 … до 30 минут, всего до 8 попыток. Постоянная
ошибка (5xx, неверный логин SMTP, SMTP не настроен) не повторяется и пишется в лог.
"""

from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Iterable, Mapping
from typing import Any

from celery import shared_task

from estimator.logging import get_logger
from estimator.notifications.mail import (
    Recipient,
    SmtpConfig,
    SmtpNotConfiguredError,
    build_message,
    deliverable,
    render_email,
    send_message,
)

log = get_logger(__name__)

MAX_RETRIES = 8
BACKOFF_SECONDS = 30
BACKOFF_MAX_SECONDS = 1800


def is_transient(exc: BaseException) -> bool:
    """Временный ли сбой: сеть, таймаут, разрыв соединения, ответ 4xx."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return all(400 <= code < 500 for code, _ in exc.recipients.values())
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    return isinstance(exc, smtplib.SMTPServerDisconnected | OSError)


def retry_delay(attempt: int) -> int:
    return min(BACKOFF_SECONDS * 2**attempt, BACKOFF_MAX_SECONDS)


async def _load_config_from_db() -> SmtpConfig:
    from sqlalchemy.ext.asyncio import create_async_engine

    from estimator.config import get_settings
    from estimator.notifications.mail.config import load_smtp_settings
    from estimator.security.crypto import get_cipher

    engine = create_async_engine(get_settings().database_url.get_secret_value())
    try:
        async with engine.connect() as conn:
            server, password = await load_smtp_settings(conn)
    finally:
        await engine.dispose()
    return SmtpConfig.from_settings(server, password, get_cipher() if password else None)


def load_config(smtp_override: Mapping[str, Any] | None) -> SmtpConfig:
    if smtp_override is not None:
        from estimator.security.crypto import get_cipher

        password = smtp_override.get("password")
        return SmtpConfig.from_settings(
            smtp_override.get("server"), password, get_cipher() if password else None
        )
    return asyncio.run(_load_config_from_db())


@shared_task(name="estimator.notifications.send_email", bind=True, max_retries=MAX_RETRIES)
def send_email(
    self: Any,
    kind: str,
    to: str,
    fields: dict[str, Any],
    smtp_override: dict[str, Any] | None = None,
    alert_channel: str | None = None,
) -> str:
    """Отправить письмо ``kind`` на адрес ``to``. Возвращает ``sent`` или ``skipped``.

    ``alert_channel`` (``old_smtp``/``new_smtp``) — письмо оповещения ИБ о смене SMTP: если оно
    не ушло окончательно, фиксируется «оповещение не доставлено» (SEC-011).
    """
    rendered = render_email(kind, fields)  # ошибка шаблона — ошибка кода, без повторов
    config = load_config(smtp_override)
    try:
        send_message(config, build_message(config, to, rendered))
    except SmtpNotConfiguredError:
        log.warning("email_skipped_smtp_not_configured", kind=kind)
        _undelivered(fields, alert_channel)
        return "skipped"
    except Exception as exc:
        if is_transient(exc) and self.request.retries < MAX_RETRIES:
            log.warning(
                "email_retry",
                kind=kind,
                error_type=type(exc).__name__,
                attempt=self.request.retries + 1,
            )
            raise self.retry(exc=exc, countdown=retry_delay(self.request.retries)) from exc
        log.error("email_failed", kind=kind, error_type=type(exc).__name__)
        _undelivered(fields, alert_channel)
        raise
    return "sent"


def _undelivered(fields: Mapping[str, Any], channel: str | None) -> None:
    if channel is None:
        return
    from estimator.security.alerts.tasks import record_undelivered

    record_undelivered(str(fields.get("alert")), channel)


def enqueue_email(
    kind: str,
    recipients: Iterable[Recipient],
    fields: Mapping[str, Any],
    *,
    smtp_override: Mapping[str, Any] | None = None,
    alert_channel: str | None = None,
) -> int:
    """Поставить письмо в очередь каждому допустимому получателю. Возвращает число писем."""
    render_email(kind, fields)  # проверить поля сразу, а не в worker
    addresses = deliverable(kind, recipients)
    override = dict(smtp_override) if smtp_override else None
    for address in addresses:
        if alert_channel is None:
            send_email.delay(kind, address, dict(fields), override)
        else:
            send_email.delay(kind, address, dict(fields), override, alert_channel)
    return len(addresses)
