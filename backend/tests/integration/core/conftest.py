"""Фикстуры API-тестов трека CORE: приложение целиком (как у AUTH), сессии без входа по паролю,
шина событий в памяти. Каждый ответ сверяется с contracts/openapi.yaml (хук фикстуры ``api``)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import COOKIE_NAME, SessionService
from estimator.db.enums import SystemRole
from estimator.db.models.dictionaries import Phase
from estimator.db.session import run_after_commit
from estimator.realtime import bus
from estimator.realtime.bus.memory import InMemoryBus
from estimator.security.web.csrf import CSRF_HEADER
from tests.integration.auth.conftest import api, clock, complete_setup, encryption_key  # noqa: F401
from tests.integration.auth.helpers import make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def events() -> Iterator[InMemoryBus]:
    recorder = InMemoryBus()
    previous = bus.set_bus(recorder)
    yield recorder
    bus.set_bus(previous)


async def deliver_events(db: AsyncSession) -> None:
    """Зафиксировать точку сохранения теста и выполнить хуки after-commit (отправку событий)."""
    await db.commit()
    await run_after_commit(db)


class Actor:
    """Клиент API от имени пользователя (сессия создаётся напрямую, без входа по паролю)."""

    def __init__(self, world: World, user_id: uuid.UUID, sid: str, csrf: str) -> None:
        self.world = world
        self.id = user_id
        self.sid = sid
        self.csrf = csrf

    def _use(self) -> httpx.AsyncClient:
        client = self.world.api
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, self.sid)
        return client

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self._use().get(f"/api/v1{path}", **kw)

    async def post(self, path: str, **kw: Any) -> httpx.Response:
        return await self._use().post(f"/api/v1{path}", headers={CSRF_HEADER: self.csrf}, **kw)

    async def patch(self, path: str, **kw: Any) -> httpx.Response:
        return await self._use().patch(f"/api/v1{path}", headers={CSRF_HEADER: self.csrf}, **kw)

    async def put(self, path: str, **kw: Any) -> httpx.Response:
        return await self._use().put(f"/api/v1{path}", headers={CSRF_HEADER: self.csrf}, **kw)

    async def delete(self, path: str, **kw: Any) -> httpx.Response:
        return await self._use().delete(f"/api/v1{path}", headers={CSRF_HEADER: self.csrf}, **kw)


class World:
    def __init__(
        self, db: AsyncSession, client: httpx.AsyncClient, service: SessionService
    ) -> None:
        self.db = db
        self.api = client
        self.service = service

    async def actor(self, *roles: SystemRole, mfa: bool = True) -> Actor:
        user = await make_user(self.db, *roles)
        return await self.session_for(user.id, *roles, mfa=mfa)

    async def session_for(self, user_id: uuid.UUID, *roles: SystemRole, mfa: bool = True) -> Actor:
        """Новая сессия пользователя («другой браузер»)."""
        sid, record = await self.service.create(
            self.db, user_id, roles, SessionPolicy(), ip="10.1.2.3", mfa_passed=mfa
        )
        return Actor(self, user_id, sid, record.csrf)

    async def phases(self) -> dict[str, uuid.UUID]:
        rows = await self.db.execute(select(Phase.name, Phase.id).where(Phase.is_active))
        return dict(rows.all())


@pytest.fixture
async def world(
    db_session: AsyncSession,
    api: httpx.AsyncClient,  # noqa: F811
    redis_client: Redis,
    clock: Any,  # noqa: F811
) -> World:
    await complete_setup(db_session)
    return World(db_session, api, SessionService(redis_client, clock))
