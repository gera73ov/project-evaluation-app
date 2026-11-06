"""Заголовки безопасности и CSP с nonce (SEC-007; SEC-WEB-03, SEC-WEB-05, CL-05).

ASGI-middleware ставит заголовки на **все** ответы приложения, включая ошибки:

* ``X-Content-Type-Options``, ``Referrer-Policy``, ``Permissions-Policy``,
  ``Cross-Origin-Opener-Policy`` — как в SEC-WEB-03;
* ``Cache-Control: no-store`` — для ``/api/*``;
* CSP: для HTML — политика SEC-WEB-03 с новым nonce на каждый ответ; nonce подставляется в
  тело вместо :data:`NONCE_PLACEHOLDER` (``<meta name="csp-nonce" content="…">`` в index.html,
  Emotion берёт его оттуда). Для остальных ответов — запрещающая политика (JSON не исполняется).

CORS не включён: без ``Access-Control-Allow-Origin`` браузер не отдаст ответ чужому сайту
(SEC-WEB-05). Статику и ошибки Nginx закрывает INF-009 тем же набором заголовков.
"""

from __future__ import annotations

import secrets

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NONCE_PLACEHOLDER = b"__CSP_NONCE__"
#: Страницы, которым политика с nonce не подходит (Swagger UI вне prod грузит скрипты сам).
CSP_EXEMPT = frozenset({"/api/docs", "/api/docs/oauth2-redirect"})

COMMON_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def html_csp(nonce: str, host: str) -> str:
    """Политика SEC-WEB-03 для страницы приложения."""
    connect = "connect-src 'self'" + (f" wss://{host}" if host else "")
    return (
        "default-src 'self'; script-src 'self'; "
        f"style-src 'self' 'nonce-{nonce}'; img-src 'self' data:; {connect}; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    )


def new_nonce() -> str:
    return secrets.token_urlsafe(18)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        host = _host(scope)
        state: dict[str, object] = {"html": False, "start": None, "body": []}

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in COMMON_HEADERS.items():
                    headers[name] = value
                if path.startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
                is_html = headers.get("content-type", "").startswith("text/html")
                if path in CSP_EXEMPT:
                    await send(message)
                    return
                if not is_html:
                    headers["Content-Security-Policy"] = API_CSP
                    await send(message)
                    return
                state["html"] = True
                state["start"] = message
                return
            if message["type"] == "http.response.body" and state["html"]:
                chunks: list[bytes] = state["body"]  # type: ignore[assignment]
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                nonce = new_nonce()
                body = b"".join(chunks).replace(NONCE_PLACEHOLDER, nonce.encode())
                start: Message = state["start"]  # type: ignore[assignment]
                headers = MutableHeaders(scope=start)
                headers["Content-Security-Policy"] = html_csp(nonce, host)
                headers["Content-Length"] = str(len(body))
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped_send)


def _host(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"host":
            return value.decode("latin-1").strip()
    return ""
