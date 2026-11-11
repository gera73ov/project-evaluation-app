"""CORE-026: кэш итогов ``project_totals`` — пересчёт ставится после правки, переполнение не
роняет задачу."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.domain.calc import money as calc_money
from estimator.services.money.totals import cached
from estimator.services.projects import totals
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("ARCH-03")]


@pytest.mark.spec("FR-HOME-04")
async def test_totals_refresh(
    world: World, db_session: AsyncSession, totals_queue: list[uuid.UUID]
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await deliver_events(db_session)
    totals_queue.clear()

    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    await deliver_events(db_session)
    assert s.pid in totals_queue  # правка дерева ставит пересчёт (задержка DEBOUNCE_SECONDS)
    assert totals.DEBOUNCE_SECONDS <= 10

    assert await totals.recompute(db_session, s.pid)
    row = (await cached(db_session, [s.pid], [s.pid]))[s.pid]
    assert row.e == Decimal("14.95")
    assert row.p80 is not None
    assert row.money is not None
    assert (row.money.quote_cur, row.money.rates_missing) == (None, True)  # ставок нет

    put = await s.moderator.put(
        f"/projects/{s.pid}/money",
        json={
            "rates": [
                {"discipline_id": str(s.backend), "rate_rub": "1000"},
                {"discipline_id": None, "rate_rub": "1000"},
            ]
        },
    )
    assert put.status_code == 200, put.text
    totals_queue.clear()
    await deliver_events(db_session)
    assert totals_queue == [s.pid]
    assert await totals.recompute(db_session, s.pid)
    row = (await cached(db_session, [s.pid], [s.pid]))[s.pid]
    assert row.money is not None
    assert row.money.rates_missing is False
    assert row.money.quote_cur == Decimal(put.json()["figures"]["p80"]["total_cur"])
    assert row.money.currency == "RUB"
    # без money.read денег в выдаче нет
    hidden = (await cached(db_session, [s.pid], []))[s.pid]
    assert (hidden.money, hidden.e) == (None, row.e)
    assert not await totals.recompute(db_session, uuid.uuid4())


@pytest.mark.spec("BR-MONEY-04")
async def test_totals_overflow(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    await s.moderator.put(
        f"/projects/{s.pid}/money",
        json={
            "rates": [
                {"discipline_id": str(s.backend), "rate_rub": "1000"},
                {"discipline_id": None, "rate_rub": "1000"},
            ]
        },
    )
    monkeypatch.setattr(calc_money, "MONEY_LIMIT", Decimal(10))
    monkeypatch.setattr(calc_money, "HOURS_CACHE_LIMIT", Decimal(10))
    assert await totals.recompute(db_session, s.pid)
    row = (await cached(db_session, [s.pid], [s.pid]))[s.pid]
    assert row.money is not None
    assert (row.e, row.p80, row.p90, row.money.quote_cur) == (None, None, None, None)


async def test_totals_daily_row(world: World, db_session: AsyncSession) -> None:
    """Одна строка ``project_totals_daily`` на день (по поясу приложения); повтор в тот же день
    перезаписывает строку итогом на последний пересчёт."""
    import datetime as dt

    from estimator.db.models.projects import Project
    from estimator.services.money import totals as money_totals

    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    project = await db_session.get(Project, s.pid)
    assert project is not None
    day1 = dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.UTC)
    await money_totals.refresh(db_session, project, now=day1)
    first = await money_totals.daily(db_session, s.pid)
    assert [d.e for d in first] == [Decimal("14.95")]

    await _leaf(s.backend_expert, s, branch.id, "Выход", o="8", r="12", p="20")
    await db_session.refresh(project)
    await money_totals.refresh(db_session, project, now=day1 + dt.timedelta(hours=2))
    await money_totals.refresh(db_session, project, now=day1 + dt.timedelta(days=1))
    rows = await money_totals.daily(db_session, s.pid)
    assert [d.date for d in rows] == [dt.date(2026, 11, 2), dt.date(2026, 11, 3)]
    assert rows[0].e == rows[1].e
    assert rows[0].e is not None
    assert rows[0].e > Decimal("14.95")  # день 1 — итог последнего пересчёта
