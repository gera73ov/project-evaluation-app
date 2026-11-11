"""QA-007 · TC-SEC-07: закрытые заметки не видны эксперту и ревьюеру ни в API, ни в WS
(FR-NOTE-01). Обход всех GET-эндпоинтов контракта: ни текста заметок, ни их счётчиков."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.core.conftest import World
from tests.security.crawl import crawl, find
from tests.security.stocked import NOTE_MARK, stocked

from estimator.db.enums import SystemRole
from estimator.realtime.bus.memory import InMemoryBus

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-07"), pytest.mark.spec("FR-NOTE-01")]


def _note_key(key: str, value: object = None) -> bool:
    return "note" in key.lower()


async def test_notes_hidden_from_expert_and_reviewer(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    st = await stocked(world, db_session)
    # WS: события заметок — только в канал :notes; эксперт на него не подписывается
    # (test_ws_api.py::test_expert_gets_no_money_channel), в общем канале их нет
    base = events.on(f"project:{st.s.pid}")
    assert base
    assert find(base, _note_key, lambda t: NOTE_MARK in t) == []
    assert find(events.on(f"project:{st.s.pid}:notes"), lambda *_: False, lambda t: NOTE_MARK in t)

    url = f"/projects/{st.s.pid}/notes"
    for actor in (st.s.backend_expert, st.reviewer):
        assert (await actor.get(url)).status_code == 403
        assert (await actor.post(url, json={"body": "x"})).status_code == 403
        seen = await crawl(actor, st.ids)
        assert len(seen.bodies) >= 15, sorted(seen.bodies)  # обход действительно что-то видел
        leaks = {p: find(b, _note_key, lambda t: NOTE_MARK in t) for p, b in seen.bodies.items()}
        assert {p: v for p, v in leaks.items() if v} == {}

    # контроль обхода: модератор те же заметки видит
    moderator = await crawl(st.s.moderator, st.ids)
    assert find(moderator.bodies["/projects/{id}/notes"], _note_key, lambda t: NOTE_MARK in t)


async def test_presale_head_reads_but_does_not_write(
    world: World, db_session: AsyncSession
) -> None:
    st = await stocked(world, db_session)
    head = await world.actor(SystemRole.PRESALE_HEAD)
    url = f"/projects/{st.s.pid}/notes"
    listed = await head.get(url)
    assert listed.status_code == 200, listed.text
    assert NOTE_MARK in listed.text
    assert (await head.post(url, json={"body": "x"})).status_code == 403
