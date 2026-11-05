"""Структурные JSON-логи (INF-002).

NFR-MNT-04: одна JSON-строка на событие с полями ``time, level, request_id, user_id,
project_id, event``. Контекст (``request_id``, ``user_id``, ``project_id``) хранится в
contextvars и подставляется автоматически: ``request_id`` — middleware ниже, ``user_id`` и
``project_id`` — треки AUTH и CORE через :func:`bind_context`.
SEC-AUTH-04: секреты в логи не попадают — значения ключей из :data:`SECRET_KEYS` заменяются.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

#: Подстроки имён полей, значения которых никогда не пишутся в лог (SEC-AUTH-04).
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
    "database_url",
    "redis_url",
    "broker_url",
)
REDACTED = "***"

#: Поля, которые есть в каждой записи (NFR-MNT-04), даже если пусты.
BASE_FIELDS = ("request_id", "user_id", "project_id")


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_secret_key(k) else _redact(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(v, depth + 1) for v in value)
    return value


def _is_secret_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(s in lowered for s in SECRET_KEYS)


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Процессор structlog: скрыть значения секретных полей (SEC-AUTH-04)."""
    for key in list(event_dict):
        if key == "event":
            continue
        if _is_secret_key(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def add_base_fields(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Процессор structlog: обязательные поля NFR-MNT-04 присутствуют всегда."""
    for name in BASE_FIELDS:
        event_dict.setdefault(name, None)
    return event_dict


def configure_logging(level: str = "INFO", *, stream: str = "stdout") -> None:
    """Настроить structlog и стандартный logging на вывод JSON.

    ``stream="stderr"`` — для CLI, чтобы логи не смешивались с выводом команды.
    """
    shared: list[Any] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
        add_base_fields,
        redact_secrets,
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[*shared, structlog.processors.JSONRenderer(ensure_ascii=False)],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=_StreamLoggerFactory(stream),
        cache_logger_on_first_use=False,
    )
    # Сообщения библиотек (uvicorn, celery, sqlalchemy) — в тот же JSON-формат
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    handler = logging.StreamHandler(getattr(sys, stream))
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        lib = logging.getLogger(name)
        lib.handlers[:] = []
        lib.propagate = True


class _StreamLoggerFactory:
    """Берёт ``sys.stdout``/``sys.stderr`` в момент записи (важно для тестов и перенаправлений)."""

    def __init__(self, stream: str) -> None:
        self._stream = stream

    def __call__(self, *_args: Any) -> structlog.PrintLogger:
        return structlog.PrintLogger(file=getattr(sys, self._stream))


def get_logger(name: str | None = None) -> Any:
    """Логгер structlog; ``event`` — первый позиционный аргумент вызова."""
    return structlog.get_logger(name)


def bind_context(**values: Any) -> None:
    """Добавить поля (``user_id``, ``project_id``…) в контекст текущего запроса или задачи."""
    bind_contextvars(**values)


def new_request_id(incoming: str | None = None) -> str:
    """Принять входящий ``X-Request-ID``, если он безопасен, иначе выдать новый UUID."""
    if incoming and _REQUEST_ID_RE.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestIdMiddleware:
    """ASGI-middleware: ``request_id`` на каждый HTTP-запрос и WebSocket-соединение.

    Чистый ASGI (не ``BaseHTTPMiddleware``), чтобы не ломать WebSocket и потоковые ответы.
    Значение кладётся в контекст логов и в заголовок ответа ``X-Request-ID``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = None
        for name, value in scope.get("headers", []):
            if name.decode("latin-1").lower() == REQUEST_ID_HEADER:
                incoming = value.decode("latin-1")
                break
        request_id = new_request_id(incoming)
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            clear_contextvars()
