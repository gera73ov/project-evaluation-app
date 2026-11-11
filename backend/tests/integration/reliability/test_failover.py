"""QA-026 · надёжность на настоящих процессах API (NFR-REL-04, NFR-REL-05, ARCH-05, 18.3).

* Процесс API убит (``SIGKILL``) посреди серии правок: ни одна подтверждённая правка не потеряна,
  работа продолжается через вторую реплику.
* Поочерёдный перезапуск ``api``: клиент WebSocket остановленной реплики переподключается к
  другой с ``since`` и получает пропущенное; новая реплика сразу обслуживает запросы.
* Потеря данных Redis (перезапуск без сохранения): сессии пропали — 401 и вход заново; данные
  проекта целы. Ключи сессий удаляются точечно, а не ``FLUSHDB``: Redis общий для параллельных
  процессов тестов.
"""

from __future__ import annotations

import signal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import SessionService, id_hash
from estimator.auth.sessions.service import KEY_PREFIX
from estimator.db.models.tree import ChangeLog
from tests.integration.concurrency.test_two_api_processes import (
    World2,
    live_database_url,
    live_db,
    world2,
)
from tests.plugins.processes import StartApi

__all__ = ["live_database_url", "live_db", "world2"]

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-REL-04"),
              pytest.mark.spec("NFR-REL-05"), pytest.mark.spec("ARCH-05")]  # fmt: skip

SERIES = 30


async def test_killed_process_loses_no_confirmed_edit(
    world2: World2, live_db: async_sessionmaker[AsyncSession]
) -> None:
    w = world2
    confirmed: list[tuple[int, str]] = []  # (project_version, значение R)
    api = w.first
    for i in range(SERIES):
        if i == SERIES // 2:
            w.first.process.send_signal(signal.SIGKILL)  # авария процесса посреди серии
            w.first.process.wait()
            api = w.second
        node = await w.node(api, w.a)
        value = str(100 + i)
        done = await w.patch(api, w.a, node["version"], r=value)
        assert done.status_code == 200, done.text
        confirmed.append((done.json()["project_version"], value))

    async with live_db() as db:
        logged = set((await db.scalars(
            select(ChangeLog.version).where(ChangeLog.project_id == w.pid)
        )).all())  # fmt: skip
    missing = [v for v, _ in confirmed if v not in logged]
    assert missing == [], missing
    assert (await w.node(w.second, w.b))["r"] == confirmed[-1][1]


async def test_rolling_restart_reconnects_without_loss(
    world2: World2, api_processes: StartApi
) -> None:
    w = world2
    tree = await w.rest(w.first, w.b, "GET", f"/projects/{w.pid}/tree")
    since = tree.json()["project_version"]
    b = await w.client(w.first, w.b, since=since)

    # реплика 1 уходит на перезапуск (SIGTERM — штатная остановка), клиент теряет соединение
    w.first.stop()
    assert await b.closed() is not None
    for value in ("41", "42", "43"):
        node = await w.node(w.second, w.a)
        assert (await w.patch(w.second, w.a, node["version"], r=value)).status_code == 200

    # клиент переподключается к живой реплике и догоняет пропущенное
    b = await w.client(w.second, w.b, since=since)
    caught = [await b.event("node.updated") for _ in range(3)]
    assert [e["data"]["node"]["r"] for e in caught] == ["41", "42", "43"]

    # новая реплика 1 поднялась; затем перезапускается реплика 2
    [fresh] = api_processes(1, env=w.env)  # та же база и тот же Redis
    w.second.stop()
    assert await b.closed() is not None
    node = await w.node(fresh, w.a)
    assert (await w.patch(fresh, w.a, node["version"], r="44")).status_code == 200
    again = await w.client(fresh, w.b, since=caught[-1]["project_version"])
    assert (await again.event("node.updated"))["data"]["node"]["r"] == "44"


async def test_redis_loss_logs_users_out_but_keeps_data(
    world2: World2, redis_client: Redis, live_db: async_sessionmaker[AsyncSession]
) -> None:
    w = world2
    node = await w.node(w.first, w.a)
    assert (await w.patch(w.first, w.a, node["version"], r="77")).status_code == 200

    # Redis перезапустился без данных: сессий больше нет
    for who in (w.a, w.b, w.moderator):
        await redis_client.delete(KEY_PREFIX + id_hash(who.sid).hex())
    for api in (w.first, w.second):
        gone = await w.rest(api, w.a, "GET", f"/projects/{w.pid}/tree")
        assert (gone.status_code, gone.json()["code"]) == (401, "UNAUTHENTICATED"), gone.text

    # вход заново — данные проекта на месте
    service = SessionService(redis_client)
    async with live_db() as db, db.begin():
        sid, record = await service.create(db, w.a.user_id, (), SessionPolicy(), ip="10.0.0.1",
                                           mfa_passed=True)  # fmt: skip
    w.a.sid, w.a.csrf = sid, record.csrf
    assert (await w.node(w.second, w.a))["r"] == "77"
