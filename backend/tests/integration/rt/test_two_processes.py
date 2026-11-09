"""RT-004 · два процесса API за общим Redis (SPEC 13.2–13.3, NFR-REL-05).

Событие с процесса 1 доходит до клиента процесса 2; деньги — только подписчику с правом.
Процессы Uvicorn настоящие, поэтому данные фиксируются в отдельной базе с миграциями.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import SessionEnded, SessionService, id_hash
from estimator.db.enums import ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.dictionaries import Discipline
from estimator.db.models.projects import Project, ProjectMember
from estimator.realtime.bus import build_event
from estimator.realtime.pubsub import RedisBus, publish_control
from estimator.realtime.revoke import session_ended_message
from tests.conftest import REDIS_ENV_VAR
from tests.integration.auth.conftest import complete_setup
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import alembic
from tests.integration.rt.conftest import Client
from tests.plugins.database import ENV_VAR, database_name, recreate_database, worker_name
from tests.plugins.processes import StartApi, WsConnect

pytestmark = [pytest.mark.integration, pytest.mark.spec("13.3"), pytest.mark.spec("NFR-REL-05")]


@pytest.fixture
def live_database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    server_url = os.environ.get(ENV_VAR)
    if not server_url or not os.environ.get(REDIS_ENV_VAR):
        pytest.skip(f"нужны {ENV_VAR} и {REDIS_ENV_VAR}")
    name = database_name(f"{worker_name(request.config)}_rt")
    asyncio.run(recreate_database(server_url, name))
    url = make_url(server_url).set(database=name).render_as_string(hide_password=False)
    alembic(url, "upgrade", "head")
    yield url
    asyncio.run(recreate_database(server_url, name, drop_only=True))


@pytest.fixture
async def live_db(live_database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(live_database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_event_from_process_1_reaches_client_of_process_2(
    live_database_url: str,
    live_db: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    api_processes: StartApi,
    ws_connect: WsConnect,
) -> None:
    redis_url = os.environ[REDIS_ENV_VAR]
    service = SessionService(redis_client)
    async with live_db() as db, db.begin():
        await complete_setup(db)
        project = Project(
            name="Портал дилеров",
            customer="ООО Ромашка",
            pm_percent=Decimal(18),
            status=ProjectStatus.ESTIMATION,
        )
        db.add(project)
        await db.flush()
        backend = (await db.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))).one()
        moderator = await make_user(db, SystemRole.MODERATOR)
        expert = await make_user(db)
        db.add_all([
            ProjectMember(project_id=project.id, user_id=moderator.id, role=ProjectRole.MODERATOR),
            ProjectMember(project_id=project.id, user_id=expert.id, role=ProjectRole.EXPERT,
                          discipline_id=backend),
        ])  # fmt: skip
        await db.flush()
        m_sid, _ = await service.create(
            db, moderator.id, [SystemRole.MODERATOR], SessionPolicy(), ip="10.0.0.1",
            mfa_passed=True,
        )  # fmt: skip
        e_sid, _ = await service.create(db, expert.id, [], SessionPolicy(), ip="10.0.0.2")

    first, second = api_processes(
        2, env={"DATABASE_URL": live_database_url, "REDIS_URL": redis_url}
    )

    async def client(url: str, sid: str) -> Client:
        conn = await ws_connect(f"{url}/api/v1/ws", headers={
            "Cookie": f"__Host-session={sid}", "Origin": "https://localhost",
        })  # fmt: skip
        return Client(conn)

    e = await client(second.ws_base_url, e_sid)
    reply = await e.subscribe(project.id)
    assert reply["type"] == "ack", reply
    assert reply["result"]["channels"] == [f"project:{project.id}"]
    m = await client(first.ws_base_url, m_sid)
    assert len((await m.subscribe(project.id))["result"]["channels"]) == 3

    # присутствие: подписка на процессе 1 видна клиенту процесса 2
    both = {str(moderator.id), str(expert.id)}
    await e.wait(lambda x: x.get("event") == "presence"
                 and {u["id"] for u in x["data"]["users"]} == both)  # fmt: skip

    # событие шины от любого процесса — всем подписчикам канала, деньги — только модератору
    bus = RedisBus(redis_client)
    base = f"project:{project.id}"
    await bus.send(build_event(f"{base}:money", "money.updated",
                               {"totals": {"cost_rub": "1", "quote_rub": "1", "quote_cur": "1"}},
                               project_version=2))  # fmt: skip
    await bus.send(build_event(base, "project.updated",
                               {"changes": {"name": "Б"}, "author": None},
                               project_version=3))  # fmt: skip
    await m.event("money.updated")
    for c in (m, e):
        assert (await c.event("project.updated"))["project_version"] == 3
    assert not e.events("money.updated")

    # завершение сессии на одном процессе закрывает её WebSocket на другом
    await publish_control(
        redis_client,
        session_ended_message(SessionEnded(expert.id, id_hash(e_sid), "blocked")),
    )
    assert (await e.event("session.ended"))["data"] == {"reason": "user_blocked"}
    assert await e.closed() == 4401
    left = await m.wait(lambda x: x.get("event") == "presence" and len(x["data"]["users"]) == 1)
    assert left["data"]["users"][0]["id"] == str(moderator.id)
    assert uuid.UUID(left["data"]["users"][0]["id"]) == moderator.id
