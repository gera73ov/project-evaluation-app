"""Отправка письма по SMTP (NTF-002; FR-NOTIF-02).

TLS проверяет сертификат сервера (контекст по умолчанию); ``security = none`` — только для
внутреннего релея, мастер настройки предупреждает о нём. Пароль SMTP в логи не попадает
(SEC-AUTH-04): в лог пишутся только хост, порт и класс ошибки.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from estimator.logging import get_logger
from estimator.notifications.mail.config import SmtpConfig

log = get_logger(__name__)


class SmtpNotConfiguredError(RuntimeError):
    """SMTP не настроен (``smtp.server.host`` или адрес отправителя пусты)."""


def _connect(config: SmtpConfig, context: ssl.SSLContext) -> smtplib.SMTP:
    if config.security == "tls":
        return smtplib.SMTP_SSL(
            config.host or "", config.port, timeout=config.timeout_seconds, context=context
        )
    client = smtplib.SMTP(config.host or "", config.port, timeout=config.timeout_seconds)
    if config.security == "starttls":
        client.starttls(context=context)
    return client


def send_message(
    config: SmtpConfig, message: EmailMessage, *, context: ssl.SSLContext | None = None
) -> None:
    """Отправить письмо. Ошибки SMTP и сети пробрасываются (задача Celery повторит отправку)."""
    if not config.configured:
        raise SmtpNotConfiguredError("SMTP не настроен")
    context = context or ssl.create_default_context()
    client = _connect(config, context)
    try:
        if config.username:
            client.login(config.username, config.password or "")
        client.send_message(message)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            client.close()
    log.info(
        "email_sent",
        smtp_host=config.host,
        smtp_port=config.port,
        recipients=len(message.get_all("To", [])),
    )
