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

from estimator.logging import get_logger

log = get_logger(__name__)

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
            await _reject(scope, send, limit)
            return
        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    if not started:
                        await _reject(scope, send, limit)
                    # приложение видит обрыв соединения и прекращает чтение
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # ответ 413 уже отправлен
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)


async def _reject(scope: Scope, send: Send, limit: int) -> None:
    # Тело — RFC 9457 из общего каталога, с error_id (API-003): middleware стоит снаружи
    # обработчиков исключений FastAPI, поэтому ответ собирается здесь
    from estimator.api.common.errors import new_error_id, problem_body

    error_id = new_error_id()
    path = scope.get("path", "")
    log.info("api_error", error_code="PAYLOAD_TOO_LARGE", status=413, error_id=error_id, path=path)
    body = json.dumps(
        problem_body(
            "PAYLOAD_TOO_LARGE",
            error_id=error_id,
            instance=path,
            extensions={"limit_bytes": limit},
        ),
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
