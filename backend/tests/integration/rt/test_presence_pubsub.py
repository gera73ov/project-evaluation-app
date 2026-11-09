"""RT-006 и RT-004 на живом Redis: список присутствия, слушатель pub/sub, служебные сообщения."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from redis.asyncio import Redis

from estimator.config import Settings
from estimator.realtime import bus
from estimator.realtime.bus import build_event
from estimator.realtime.bus.memory import InMemoryBus
from estimator.realtime.presence import TTL_SECONDS, Presence
from estimator.realtime.pubsub import CONTROL_CHANNEL, EVENTS_CHANNEL, Listener, RedisBus
from estimator.realtime.runtime import Realtime, allowed_origin_hosts
from estimator.realtime.users import user_ref
from estimator.realtime.ws.hub import Connection, ProjectAccess
from estimator.realtime.ws.protocol import CLOSE_RESTART, CLOSE_SESSION_ENDED
from tests.conftest import REDIS_ENV_VAR
from tests.integration.auth.conftest import Clock

pytestmark = [pytest.mark.integration, pytest.mark.spec("15.4")]


@pytest.fixture
def memory_bus():
    memory = InMemoryBus()
    previous = bus.set_bus(memory)
    yield memory
    bus.set_bus(previous)


@pytest.mark.spec("11.4")
async def test_presence_dedupes_users_and_drops_stale(redis_client: Redis, memory_bus) -> None:
    clock = Clock()
    presence = Presence(redis_client, clock)
    project = uuid.uuid4()
    ivanov = user_ref(uuid.uuid4(), "Иванов Иван")
    smirnova = user_ref(uuid.uuid4(), "Смирнова Анна")
    await presence.join(project, "c1", ivanov)
    await presence.join(project, "c2", ivanov)  # вторая вкладка
    await presence.join(project, "c3", smirnova)
    users, pruned = await presence.users(project)
    assert [u["full_name"] for u in users] == ["Иванов Иван", "Смирнова Анна"]
    assert not pruned
    assert len(memory_bus.names()) == 3
    assert memory_bus.events[-1]["data"]["users"] == users

    await presence.leave(project, "c1")
    assert len((await presence.users(project))[0]) == 2  # c2 ещё открыт
    await presence.leave(project, "nope")
    assert len(memory_bus.events) == 4  # отписка неизвестного соединения не рассылает

    # процесс с c3 «упал»: его запись не обновляется и через 30 с исчезает
    clock.now += TTL_SECONDS + 1
    await presence.sweep([(project, {"c2": ivanov})])
    assert memory_bus.events[-1]["data"]["users"] == [ivanov]
    await redis_client.hset(f"presence:{project}", "bad", "{")
    assert (await presence.users(project)) == ([ivanov], True)


async def test_listener_delivers_events_and_control(redis_client: Redis) -> None:
    url = os.environ[REDIS_ENV_VAR]
    events: list[dict[str, Any]] = []
    control: list[dict[str, Any]] = []

    async def on_control(message: dict[str, Any]) -> None:
        control.append(message)

    listener = Listener(url, on_event=events.append, on_control=on_control)
    listener.start()
    listener.start()  # повторный запуск не плодит задач
    await asyncio.wait_for(listener.ready.wait(), 5)
    marker = str(uuid.uuid4())
    event = build_event(f"user:{marker}", "session.ended", {"reason": "revoked"})
    await RedisBus(redis_client).send(event)
    await redis_client.publish(EVENTS_CHANNEL, b"not json")
    await redis_client.publish(EVENTS_CHANNEL, b"[1]")
    await redis_client.publish(CONTROL_CHANNEL, f'{{"kind": "x", "m": "{marker}"}}')
    async with asyncio.timeout(5):
        while not (any(e["channel"] == f"user:{marker}" for e in events)  # noqa: ASYNC110
                   and any(c.get("m") == marker for c in control)):  # fmt: skip
            await asyncio.sleep(0.02)
    await listener.stop()
    await listener.stop()
    assert not listener.ready.is_set()


async def test_listener_survives_handler_failure_and_reconnects(redis_client: Redis) -> None:
    url = os.environ[REDIS_ENV_VAR]
    seen: list[str] = []
    reconnects: list[int] = []

    def on_event(message: dict[str, Any]) -> None:
        seen.append(message["channel"])
        raise RuntimeError("сбой обработчика")

    listener = Listener(url, on_event=on_event, on_control=lambda m: None,
                        on_reconnect=lambda: reconnects.append(1))  # fmt: skip
    listener.start()
    await asyncio.wait_for(listener.ready.wait(), 5)
    marker = f"user:{uuid.uuid4()}"
    await RedisBus(redis_client).send(build_event(marker, "session.ended", {"reason": "revoked"}))
    async with asyncio.timeout(5):
        while marker not in seen:  # noqa: ASYNC110 — опрос состояния в тесте
            await asyncio.sleep(0.02)
    # оборвать соединения слушателя: он переподключится и сообщит об этом
    for c in await redis_client.client_list():
        if c.get("name") == listener.client_name:
            await redis_client.client_kill_filter(_id=c["id"])
    async with asyncio.timeout(10):
        while not reconnects:  # noqa: ASYNC110 — опрос состояния в тесте
            await asyncio.sleep(0.05)
    await listener.stop()


def _conn(user_id: uuid.UUID, session_hash: bytes = b"h") -> Connection:
    return Connection(user_id=user_id, session_id="s", session_hash=session_hash)


async def test_runtime_control_and_member_recheck(redis_client: Redis) -> None:
    settings = Settings(redis_url=os.environ[REDIS_ENV_VAR],
                        trusted_hosts=["estimator.corp", "*"])  # fmt: skip
    assert allowed_origin_hosts(settings) == {"localhost", "estimator.corp"}
    rt = Realtime(settings, redis_client)
    project = uuid.uuid4()
    alice, bob = _conn(uuid.uuid4(), b"a"), _conn(uuid.uuid4(), b"b")
    for c in (alice, bob):
        rt.hub.add(c)
        rt.hub.set_access(c, ProjectAccess(project))
    rt.on_event(build_event(f"project:{project}", "member.updated",
                            {"user_ids": [str(bob.user_id)], "change": "updated"},
                            project_version=4))  # fmt: skip
    assert bob.recheck.is_set()
    assert not alice.recheck.is_set()
    assert alice.queue.qsize() == bob.queue.qsize() == 1
    rt.on_event({"event": "member.updated", "channel": "broken", "data": {}})

    rt.on_control({"kind": "session_ended", "session_hash": "zz"})
    rt.on_control({"kind": "unknown"})
    rt.on_control({"kind": "session_ended", "session_hash": b"a".hex(), "reason": "logged_out"})
    assert alice.close_code == CLOSE_SESSION_ENDED
    assert bob.close_code is None
    rt.on_reconnect()
    assert bob.close_code == CLOSE_RESTART

    rt.hub.remove(alice)
    rt.hub.remove(bob)
    carol = _conn(uuid.uuid4())
    carol.user = user_ref(carol.user_id, "Сидоров Пётр")
    rt.hub.add(carol)
    rt.hub.set_access(carol, ProjectAccess(project))
    await rt.sweep_presence()
    assert await redis_client.hexists(f"presence:{project}", carol.id)


async def test_runtime_start_stop_switches_bus(redis_client: Redis) -> None:
    settings = Settings(redis_url=os.environ[REDIS_ENV_VAR])
    rt = Realtime(settings, redis_client)
    rt.sweep_seconds = 0.05
    before = bus.get_bus()
    await rt.start()
    try:
        assert isinstance(bus.get_bus(), RedisBus)
        await asyncio.sleep(0.15)  # круг обновления присутствия без соединений
    finally:
        await rt.stop()
    assert bus.get_bus() is before
    await rt.stop()  # повторная остановка безопасна
