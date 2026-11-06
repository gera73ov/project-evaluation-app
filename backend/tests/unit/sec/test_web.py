"""SEC-007: заголовки и CSP с nonce, лимиты тела, Origin (SEC-WEB-03/04/05/08)."""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from estimator.security.web.headers import NONCE_PLACEHOLDER, SecurityHeadersMiddleware
from estimator.security.web.limits import BodySizeLimitMiddleware, limit_for
from estimator.security.web.origin import origin_allowed

pytestmark = pytest.mark.spec("SEC-WEB-03")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def index() -> HTMLResponse:
        meta = b'<meta name="csp-nonce" content="' + NONCE_PLACEHOLDER + b'">'
        return HTMLResponse(b"<html><head>" + meta + b"</head></html>")

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/api/v1/echo")
    async def echo(payload: dict[str, str]) -> dict[str, int]:
        return {"n": len(payload)}

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="https://app.local"
    )


async def test_html_gets_fresh_nonce() -> None:
    async with await _client() as client:
        first = await client.get("/")
        second = await client.get("/")
    nonces = []
    for response in (first, second):
        csp = response.headers["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)  # type: ignore[union-attr]
        assert f'content="{nonce}"' in response.text
        assert "__CSP_NONCE__" not in response.text
        assert "wss://app.local" in csp
        assert "unsafe-inline" not in csp
        assert int(response.headers["Content-Length"]) == len(response.content)
        nonces.append(nonce)
    assert nonces[0] != nonces[1]
    assert "Cache-Control" not in first.headers


async def test_api_headers() -> None:
    async with await _client() as client:
        response = await client.get("/api/v1/ping")
        missing = await client.get("/api/v1/missing")
    for r in (response, missing):
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "same-origin"
        assert r.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
        assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert r.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert "access-control-allow-origin" not in r.headers, "CORS выключен (SEC-WEB-05)"


@pytest.mark.spec("SEC-WEB-08")
async def test_body_limits() -> None:
    assert limit_for("POST", "/api/v1/projects/abc/documents") == 50 * 1024 * 1024
    assert limit_for("POST", "/api/v1/admin/calendar") == 256 * 1024
    assert limit_for("PUT", "/api/v1/system/settings/auth") == 64 * 1024
    assert limit_for("POST", "/api/v1/anything") == 1024 * 1024
    async with await _client() as client:
        ok = await client.post("/api/v1/echo", json={"a": "b"})
        big = await client.post("/api/v1/echo", content=b"{" + b" " * (1024 * 1024) + b"}")

        async def chunks():  # без Content-Length
            for _ in range(5):
                yield b" " * (300 * 1024)

        streamed = await client.post("/api/v1/echo", content=chunks())
    assert ok.status_code == 200
    for r in (big, streamed):
        assert r.status_code == 413
        assert r.json()["code"] == "PAYLOAD_TOO_LARGE"
        assert r.json()["limit_bytes"] == 1024 * 1024
        assert r.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.spec("SEC-WEB-04")
@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://estimator.corp", True),
        ("https://ESTIMATOR.corp", True),
        ("http://estimator.corp", False),
        ("https://evil.example", False),
        ("https://estimator.corp.evil.example", False),
        ("null", False),
        (None, False),
        ("", False),
    ],
)
def test_origin(origin: str | None, allowed: bool) -> None:
    assert origin_allowed(origin, ["estimator.corp"]) is allowed
