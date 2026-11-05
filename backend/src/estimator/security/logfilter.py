"""Фильтры секретов в логах (SEC-009; SEC-AUTH-04, CL-11).

Пароли, токены, коды TOTP, cookie и заголовки авторизации не попадают ни в логи приложения,
ни в access-логи (SEC-AUTH-04). Две линии защиты:

1. **По имени поля** — значение поля, имя которого похоже на секрет, заменяется на ``***``
   на любой глубине (словари, списки, пары заголовков ASGI ``(b"cookie", b"…")``).
2. **По содержимому строки** — в любом строковом значении, в тексте события и в трассировке
   исключения маскируются ``password=…``, ``token=…``, ``Bearer …``, ``Cookie: …``,
   ``"password": "…"``, пароль в URL ``scheme://user:пароль@host``.

Access-лог Uvicorn пишется без строки запроса (:class:`AccessLogQueryFilter`): токены
активации и сброса пароля могут прийти в URL. Формат access-лога Nginx —
``deploy/nginx/log_format.conf`` (без ``$request``, ``$args``, cookie и Authorization).
"""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

REDACTED = "***"

#: Подстроки имён полей, значения которых не пишутся никогда (SEC-AUTH-04).
SECRET_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "totp",
    "api_key",
    "private_key",
    "encryption_key",
    "database_url",
    "redis_url",
    "broker_url",
)

#: Имена полей, которые секретны целиком, но как подстрока слишком частые (``status_code``,
#: ``error_code``, ``exit_code`` — не секреты, а ``code`` — код TOTP или сброса).
SECRET_EXACT = frozenset(
    {"code", "otp", "pin", "backup_code", "backup_codes", "totp_code", "csrf", "session"}
)

_MAX_DEPTH = 8

# Имена секретов в тексте: с подстрокой (``new_password``, ``smtp_password``) и точные.
_SUBSTR = r"password|passwd|pwd|secret|token|totp|api_key|cookie|authorization"
_EXACT = r"code|otp|pin|session|__host-session|backup_code"
_NAME = rf"(?:[a-z0-9_-]*(?:{_SUBSTR})[a-z0-9_-]*|{_EXACT})"

_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic|negotiate)\s+[A-Za-z0-9._~+/=-]{4,}"), r"\1 " + REDACTED),
    # Cookie: … / Set-Cookie: … / Authorization: … до конца строки
    (
        re.compile(r"(?i)\b(cookie|set-cookie|authorization|x-csrf-token)\s*:\s*[^\r\n]+"),
        r"\1: " + REDACTED,
    ),
    # password=… в строке запроса, теле формы, cookie
    (re.compile(rf"(?i)(?<![A-Za-z0-9_])({_NAME})=([^&;\s\"',]+)"), r"\1=" + REDACTED),
    # "password": "…" и 'token': '…' в JSON и repr словарей
    (
        re.compile(rf"(?i)([\"']{_NAME}[\"']\s*:\s*)([\"'])(.*?)\2"),
        r"\1\2" + REDACTED + r"\2",
    ),
    # scheme://user:пароль@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]*):[^@\s/]+@"), r"\1:" + REDACTED + "@"),
)


def is_secret_key(key: object) -> bool:
    if isinstance(key, bytes):
        key = key.decode("latin-1")
    lowered = str(key).lower()
    return lowered in SECRET_EXACT or any(s in lowered for s in SECRET_KEYS)


def redact_text(text: str) -> str:
    """Замаскировать секреты внутри строки."""
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, depth: int = 0) -> Any:
    """Рекурсивно скрыть секреты в значении любой вложенности."""
    if depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", "replace"))
    if isinstance(value, MutableMapping | dict):
        return {
            k: (REDACTED if is_secret_key(k) else redact(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        # пара заголовка (имя, значение): ASGI, httpx, requests
        if len(value) == 2 and isinstance(value[0], str | bytes) and is_secret_key(value[0]):
            name = value[0].decode("latin-1") if isinstance(value[0], bytes) else value[0]
            return (name, REDACTED)
        return [redact(v, depth + 1) for v in value]
    return value


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Процессор structlog. Ставится последним перед рендерером, после ``format_exc_info``,
    чтобы маскировать и текст трассировки."""
    for key in list(event_dict):
        if key == "event":
            if isinstance(event_dict[key], str):
                event_dict[key] = redact_text(event_dict[key])
            continue
        event_dict[key] = REDACTED if is_secret_key(key) else redact(event_dict[key])
    return event_dict


class AccessLogQueryFilter(logging.Filter):
    """Убрать строку запроса из access-лога Uvicorn (аргументы записи ``uvicorn.access``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2].split("?", 1)[0]
            record.args = (*args[:2], path, *args[3:])
        return True
