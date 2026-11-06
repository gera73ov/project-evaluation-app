"""Ограничение размера тела запроса (SEC-007; SEC-WEB-08, contracts/api-conventions.md).

ASGI-middleware: тело больше лимита — 413 ``PAYLOAD_TOO_LARGE`` с расширением ``limit_bytes``.
Проверяется и ``Content-Length`` (сразу), и фактический поток (на случай chunked). Лимит по
умолчанию — 1 МБ; исключения — :data:`BODY_LIMITS` (метод и шаблон пути ``/api/v1/...``).
Nginx ограничивает то же самое раньше (INF-009), здесь — вторая линия.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

KB = 1024
MB = 1024 * KB
DEFAULT_LIMIT = 1 * MB


@dataclass(frozen=True)
class BodyLimit:
    method: str
    pattern: re.Pattern[str]
    limit: int


def _rule(method: str, path: str, limit: int) -> BodyLimit:
    regex = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$"
    return BodyLimit(method, re.compile(regex), limit)


#: Исключения из 1 МБ (SEC-WEB-08): сертификат УЦ входит в раздел настроек ``auth``.
BODY_LIMITS: tuple[BodyLimit, ...] = (
    _rule("PUT", "/api/v1/system/settings/auth", 64 * KB),
    _rule("PATCH", "/api/v1/system/settings/auth", 64 * KB),
    _rule("POST", "/api/v1/admin/calendar", 256 * KB),
    _rule("POST", "/api/v1/projects/{id}/documents", 50 * MB),
)


def limit_for(method: str, path: str) -> int:
    for rule in BODY_LIMITS:
        if rule.method == method and rule.pattern.match(path):
            return rule.limit
    return DEFAULT_LIMIT


class _TooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["method"], scope["path"])
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send, limit)
            return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLargeError:
            if not started:
                await _reject(send, limit)


async def _reject(send: Send, limit: int) -> None:
    body = json.dumps(
        {
            "type": "about:blank",
            "title": "Слишком большой запрос",
            "status": 413,
            "code": "PAYLOAD_TOO_LARGE",
            "limit_bytes": limit,
        },
        ensure_ascii=False,
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
