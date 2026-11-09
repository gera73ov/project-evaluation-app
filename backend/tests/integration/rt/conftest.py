"""Сервер приложения в процессе теста и клиенты WebSocket (RT-003…RT-008).

``httpx.ASGITransport`` не умеет WebSocket, поэтому приложение запускается настоящим Uvicorn на
свободном порту в том же цикле событий, что и тест. Lifespan включён: шина RT-002 идёт через
Redis pub/sub, как в работе. БД — транзакция теста с откатом; соединения WebSocket и сам тест
обращаются к ней по очереди через замок (:class:`Stage`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import pytest
import uvicorn
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import ClientConnection, connect

from estimator import health
from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import COOKIE_NAME, SessionService
from estimator.config import Settings
from estimator.db.enums import ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.dictionaries import Discipline
from estimator.db.models.projects import Project, ProjectMember
from estimator.main import create_app
from estimator.realtime.runtime import Realtime
from tests.conftest import REDIS_ENV_VAR
from tests.integration.auth.conftest import Clock, complete_setup
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import as_app
from tests.plugins.processes import free_port

ORIGIN = "https://localhost"
CLIENT_IP = "10.1.2.3"


@contextlib.asynccontextmanager
async def shared_session(session: AsyncSession, lock: asyncio.Lock) -> AsyncIterator[AsyncSession]:
    async with lock:
        yield session
        await session.flush()


class Client:
    """Клиент WebSocket с буфером: ждать нужное сообщение, не теряя остальные."""

    def __init__(self, conn: ClientConnection) -> None:
        self.conn = conn
        self.seen: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any] | str) -> None:
        await self.conn.send(message if isinstance(message, str) else json.dumps(message))

    async def wait(
        self, match: Callable[[dict[str, Any]], bool], within: float = 5.0
    ) -> dict[str, Any]:
        for message in self.seen:
            if match(message):
                self.seen.remove(message)
                return message
        async with asyncio.timeout(within):
            while True:
                message = json.loads(await self.conn.recv())
                if match(message):
                    return message
                self.seen.append(message)

    async def event(self, name: str, within: float = 5.0) -> dict[str, Any]:
        return await self.wait(lambda m: m.get("event") == name, within)

    async def reply(self, req_id: str, within: float = 5.0) -> dict[str, Any]:
        return await self.wait(lambda m: m.get("req_id") == req_id, within)

    async def call(self, op: str, within: float = 5.0, **args: Any) -> dict[str, Any]:
        req_id = secrets.token_hex(4)
        await self.send({"op": op, "req_id": req_id, **args})
        return await self.reply(req_id, within)

    async def subscribe(self, project_id: uuid.UUID, **args: Any) -> dict[str, Any]:
        return await self.call("subscribe", project_id=str(project_id), **args)

    async def closed(self, within: float = 6.0) -> int | None:
        """Дождаться закрытия сервером; вернуть код закрытия."""
        with contextlib.suppress(Exception):
            async with asyncio.timeout(within):
                while True:
                    self.seen.append(json.loads(await self.conn.recv()))
        return self.conn.close_code

    def events(self, name: str) -> list[dict[str, Any]]:
        return [m for m in self.seen if m.get("event") == name]


class Stage:
    """Данные теста и подключение клиентов к серверу в процессе."""

    def __init__(
        self, db: AsyncSession, lock: asyncio.Lock, service: SessionService, port: int
    ) -> None:
        self.db = db
        self.lock = lock
        self.service = service
        self.url = f"ws://127.0.0.1:{port}/api/v1/ws"
        self.realtime: Realtime | None = None
        self._opened: list[ClientConnection] = []

    @contextlib.asynccontextmanager
    async def data(self) -> AsyncIterator[AsyncSession]:
        async with shared_session(self.db, self.lock) as db:
            yield db

    async def project(self, status: ProjectStatus = ProjectStatus.ESTIMATION) -> Project:
        async with self.data() as db:
            project = Project(name="Портал дилеров", customer="ООО Ромашка",
                              pm_percent=Decimal(18), status=status)  # fmt: skip
            db.add(project)
            await db.flush()
            return project

    async def discipline(self, name: str = "Бэкенд") -> uuid.UUID:
        async with self.data() as db:
            return (await db.scalars(select(Discipline.id).where(Discipline.name == name))).one()

    async def user(
        self,
        *roles: SystemRole,
        member: tuple[Project, ProjectRole, uuid.UUID | None] | None = None,
        mfa: bool = True,
    ) -> tuple[uuid.UUID, str]:
        """Пользователь с сессией; вернуть его id и идентификатор сессии (значение cookie)."""
        async with self.data() as db:
            user = await make_user(db, *roles)
            if member is not None:
                project, role, discipline = member
                db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role,
                                     discipline_id=discipline))  # fmt: skip
                await db.flush()
            sid, _ = await self.service.create(
                db, user.id, roles, SessionPolicy(), ip=CLIENT_IP, mfa_passed=mfa
            )
            return user.id, sid

    async def connect(
        self, sid: str | None, *, origin: str | None = ORIGIN, ip: str = CLIENT_IP
    ) -> Client:
        headers = {"X-Forwarded-For": ip}
        if sid:
            headers["Cookie"] = f"{COOKIE_NAME}={sid}"
        conn = await connect(
            self.url,
            additional_headers=headers,
            origin=origin,
            open_timeout=5,  # type: ignore[arg-type]
            max_size=2**20,
        )
        self._opened.append(conn)
        return Client(conn)

    async def close(self) -> None:
        for conn in self._opened:
            with contextlib.suppress(Exception):
                await conn.close()


@pytest.fixture
async def stage(
    db_session: AsyncSession, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stage]:
    redis_url = os.environ.get(REDIS_ENV_VAR)
    if not redis_url:
        pytest.skip(f"{REDIS_ENV_VAR} не задан")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    await as_app(db_session)
    await complete_setup(db_session)
    lock = asyncio.Lock()
    clock = Clock()
    service = SessionService(redis_client, clock)
    settings = Settings()
    app = create_app(settings, probes=health.Probes())
    realtime = Realtime(
        settings, app.state.redis, db=lambda: shared_session(db_session, lock), clock=clock
    )
    realtime.revalidate_seconds = 0.5
    app.state.realtime = realtime
    port = free_port()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="on", log_config=None,
        proxy_headers=True, forwarded_allow_ips="127.0.0.1", ws_max_size=2**20,
    )  # fmt: skip
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:  # noqa: ASYNC110 — у uvicorn.Server нет события «запущен»
            await asyncio.sleep(0.02)
    st = Stage(db_session, lock, service, port)
    st.realtime = realtime
    st.clock = clock  # type: ignore[attr-defined]
    try:
        yield st
    finally:
        await st.close()
        server.should_exit = True
        with contextlib.suppress(Exception):
            async with asyncio.timeout(10):
                await task
