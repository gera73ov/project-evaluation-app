"""Тестовое письмо (CR-009; 7.1 шаг 2, FR-NOTIF-02; ``POST /system/smtp/test``).

Письмо уходит сразу, синхронно, с параметрами формы (несохранёнными) или, без ``values``, с
сохранёнными. Ничего не записывается. Сохранённый пароль SMTP подставляется, только если
``host``, ``port`` и ``username`` формы совпадают с сохранёнными: иначе пароль из хранилища ушёл
бы на чужой сервер — тогда без пароля в форме 422. Ошибка отправки — ``ok: false`` и ``detail``.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import time
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import settings
from estimator.admin.settings import schema
from estimator.auth import passwords
from estimator.logging import get_logger
from estimator.notifications import mail
from estimator.security.crypto import get_cipher

log = get_logger(__name__)

SERVER, PASSWORD = "smtp.server", "smtp.password"
_SAME_SERVER = ("host", "port", "username")


def _detail(exc: BaseException) -> str:
    if isinstance(exc, mail.SmtpNotConfiguredError):
        return "Укажите сервер и адрес отправителя"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Сервер отклонил логин или пароль"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Сервер отклонил адрес получателя"
    if isinstance(exc, ssl.SSLError):
        return "Ошибка TLS: проверьте режим защиты и сертификат сервера"
    if isinstance(exc, TimeoutError | OSError):
        return "Сервер недоступен или не отвечает"
    return "Письмо не отправлено: ошибка SMTP"


async def _config(db: AsyncSession, values: Mapping[str, Any] | None) -> mail.SmtpConfig:
    raw = await settings.stored(db, (SERVER, PASSWORD))
    saved_server = {**schema.default(SERVER), **(raw.get(SERVER) or {})}
    saved_password = raw.get(PASSWORD)
    if not values:
        return mail.SmtpConfig.from_settings(saved_server, saved_password, get_cipher())
    problems = settings.check_values((SERVER, PASSWORD), values)
    if problems:
        raise settings.validation_error(problems)
    server = values.get(SERVER, saved_server)
    password = values.get(PASSWORD, settings.KEEP_SECRET)
    if password == settings.KEEP_SECRET:
        same = all(server.get(k) == saved_server.get(k) for k in _SAME_SERVER)
        if saved_password is not None and not same:
            raise settings.validation_error(
                [(f"/{PASSWORD}", "Сервер изменён: введите пароль SMTP заново")]
            )
        password = saved_password if same else None
    cipher = get_cipher() if password is not None and not isinstance(password, str) else None
    return mail.SmtpConfig.from_settings(server, password, cipher)


async def send(db: AsyncSession, to: str, values: Mapping[str, Any] | None) -> dict[str, Any]:
    config = await _config(db, values)
    link = await passwords.base_url(db)
    started = time.monotonic()
    detail: str | None = None
    try:
        await asyncio.to_thread(mail.send_test_email, config, to, link)
    except (mail.SmtpNotConfiguredError, smtplib.SMTPException, OSError) as exc:
        detail = _detail(exc)
        log.info("smtp_test_failed", error=type(exc).__name__)
    return {
        "ok": detail is None,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "detail": detail,
    }
