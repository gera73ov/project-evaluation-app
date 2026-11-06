"""RT-002 на живой БД: событие уходит только после COMMIT (ARCH-01, NFR-REL-04)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from estimator.config import Settings
from estimator.db import session as db
from estimator.realtime import bus
from estimator.realtime.bus.contract import EventContractError
from estimator.realtime.bus.memory import InMemoryBus

pytestmark = [pytest.mark.integration, pytest.mark.spec("ARCH-01"), pytest.mark.spec("NFR-REL-04")]

USER = str(uuid.uuid4())


@pytest.fixture
async def maker(test_database_url: str):
    engine = db.create_engine(Settings(database_url=test_database_url))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def memory() -> Iterator[InMemoryBus]:
    recorder = InMemoryBus()
    previous = bus.set_bus(recorder)
    yield recorder
    bus.set_bus(previous)


def _publish(session, reason: str = "revoked") -> None:
    bus.publish(session, f"user:{USER}", "session.ended", {"reason": reason})


async def test_event_sent_after_commit(maker, memory: InMemoryBus) -> None:
    async with db.transaction(maker) as session:
        await session.execute(text("SELECT 1"))
        _publish(session)
        assert memory.events == [], "до COMMIT событие не уходит"
    assert memory.names() == ["session.ended"]
    assert memory.events[0]["data"] == {"reason": "revoked"}


async def test_rollback_drops_event(maker, memory: InMemoryBus) -> None:
    with pytest.raises(RuntimeError):  # noqa: PT012 — откат блока проверяется целиком
        async with db.transaction(maker) as session:
            await session.execute(text("SELECT 1"))
            _publish(session)
            raise RuntimeError("откат")
    assert memory.events == []


async def test_invalid_event_fails_the_transaction(maker, memory: InMemoryBus) -> None:
    with pytest.raises(EventContractError):  # noqa: PT012
        async with db.transaction(maker) as session:
            await session.execute(text("SELECT 1"))
            _publish(session, reason="bored")  # быстрая проверка пропускает…
            bus.publish(session, f"user:{USER}", "session.ended", {"reason": "x", "why": 1})
    assert memory.events == [], "и первое событие откатилось вместе с транзакцией"


async def test_transport_failure_does_not_break_commit(maker) -> None:
    class Broken:
        async def send(self, event: bus.Event) -> None:
            raise ConnectionError("redis down")

    previous = bus.set_bus(Broken())
    try:
        async with db.transaction(maker) as session:
            await session.execute(text("SELECT 1"))
            _publish(session)
    finally:
        bus.set_bus(previous)
