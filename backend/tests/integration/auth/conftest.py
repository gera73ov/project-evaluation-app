"""Приложение целиком для API-тестов AUTH: сессия БД теста, тестовый Redis, ключ шифрования."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator import health
from estimator.auth.context import get_session_service
from estimator.auth.providers import ldap
from estimator.auth.sessions import SessionService
from estimator.config import Settings, get_settings
from estimator.db.session import db_session as db_session_dependency
from estimator.main import create_app
from estimator.redis_client import get_redis
from estimator.security.crypto import get_cipher
from estimator.security.crypto.keys import format_key, generate_key
from estimator.security.web.csrf import CSRF_COOKIE, CSRF_HEADER
from tests.contract.openapi_impl import check_response
from tests.integration.db.conftest import as_app
from tests.support.fake_ad import FakeDirectory


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", format_key(generate_key("ktest")))
    get_settings.cache_clear()
    get_cipher.cache_clear()
    yield
    get_cipher.cache_clear()


async def set_setting(db: AsyncSession, key: str, value: object) -> None:
    await db.execute(
        text(
            "INSERT INTO system_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"k": key, "v": json.dumps(value)},
    )


async def complete_setup(db: AsyncSession) -> None:
    await set_setting(db, "app.setup", {"completed_at": "2026-11-06T00:00:00Z", "steps_done": []})


@pytest.fixture
async def api(
    db_session: AsyncSession,
    redis_client: Redis,
    clock: Clock,
    encryption_key: None,
) -> AsyncIterator[httpx.AsyncClient]:
    await as_app(db_session)
    app = create_app(Settings(), probes=health.Probes())

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session
        await db_session.flush()

    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[get_session_service] = lambda: SessionService(redis_client, clock)
    app.dependency_overrides[get_redis] = lambda: redis_client
    ip = ".".join(str(secrets.randbelow(250) + 1) for _ in range(3))
    transport = httpx.ASGITransport(app=app, client=(f"10.{ip}", 1))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://test",
        event_hooks={"response": [contract_hook]},
    ) as client:
        client.app = app  # type: ignore[attr-defined]
        yield client


async def contract_hook(response: httpx.Response) -> None:
    """Каждый ответ API-теста сверяется с contracts/openapi.yaml (API-004)."""
    raw = await response.aread()
    body = json.loads(raw) if raw and "json" in response.headers.get("content-type", "") else raw
    issues = check_response(
        response.request.method,
        response.request.url.path,
        response.status_code,
        response.headers.get("content-type", ""),
        body,
    )
    assert not issues, "ответ расходится с контрактом:\n" + "\n".join(issues)


def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    return {CSRF_HEADER: token} if token else {}


@pytest.fixture
def fake_ad() -> Iterator[FakeDirectory]:
    """Имитация AD вместо настоящего каталога (AUTH-013…019 до стенда Samba AD)."""
    directory = FakeDirectory()
    ldap.set_directory_factory(lambda _config: directory)
    yield directory
    ldap.set_directory_factory(None)
