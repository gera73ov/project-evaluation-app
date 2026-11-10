"""CORE-030: деньги проекта — права и TOTP, ставки, валюта, курс, НДС, итоги, аудит без сумм,
событие ``money.updated``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.dictionaries import VatRate
from estimator.db.models.tree import ProjectJournal
from estimator.realtime.bus.memory import InMemoryBus
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUTHZ-04")]


async def _audit(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'project.money.changed' "
            "AND object_id = :o ORDER BY id"
        ),
        {"o": str(project_id)},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.spec("BR-MONEY-01")
async def test_money_access(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/money"
    denied = await s.backend_expert.get(url)
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    no_totp = await world.session_for(s.moderator.id, SystemRole.MODERATOR, mfa=False)
    blocked = await no_totp.get(url)
    assert (blocked.status_code, blocked.json()["code"]) == (403, "TOTP_REQUIRED")
    head = await world.actor(SystemRole.PRESALE_HEAD)
    seen = await head.get(url)
    assert seen.status_code == 200, seen.text
    assert (await head.put(url, json={"currency": "USD"})).status_code == 403
    body = (await s.moderator.get(url)).json()
    assert (body["currency"], body["exchange_rate"]) == ("RUB", "1")
    assert {r["discipline_id"] for r in body["rates"]} == {str(s.backend), str(s.frontend), None}
    assert all(r["rate_rub"] is None for r in body["rates"])


@pytest.mark.spec("BR-MONEY-02")
@pytest.mark.spec("BR-MONEY-03")
@pytest.mark.spec("BR-MONEY-05")
async def test_put_money(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/money"
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")

    before = (await s.moderator.get(url)).json()
    assert before["rates_missing"] == [str(s.backend), "pm"]
    assert before["figures"] == {}

    no_vat = (await db_session.scalars(select(VatRate.id).where(VatRate.percent.is_(None)))).first()
    put = await s.moderator.put(
        url,
        json={
            "currency": "USD",
            "exchange_rate": "90,5",
            "vat_rate_id": str(no_vat),
            "rates": [
                {"discipline_id": str(s.backend), "rate_rub": "3000"},
                {"discipline_id": None, "rate_rub": "2500"},
            ],
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert (body["currency"], body["exchange_rate"], body["vat_percent"]) == ("USD", "90.5", None)
    assert body["rates_missing"] == []
    e = body["figures"]["e"]
    assert e["total_rub"] == str(sum(int(r["amount"]) for r in e["rows_rub"]))
    assert e["vat_rub"] is None
    assert {r["discipline_id"] for r in e["rows_rub"]} == {str(s.backend), str(s.frontend), None}
    assert set(body["figures"]) == {"e", "p80", "p90"}

    # аудит — только факт и поля, без сумм; значения — в журнале с признаком денег
    [details] = await _audit(db_session, s.pid)
    assert details == {
        "fields": ["currency", "exchange_rate", "vat_rate", "rate", "pm_rate"],
        "discipline_ids": [str(s.backend)],
        "project_id": str(s.pid),
    }
    entry = (
        await db_session.scalars(
            select(ProjectJournal).where(
                ProjectJournal.project_id == s.pid,
                ProjectJournal.action == "project.money.changed",
            )
        )
    ).one()
    assert entry.is_money
    assert entry.changes["rate:pm"] == [None, "2500"]

    await deliver_events(db_session)
    [event] = events.on(f"project:{s.pid}:money")
    assert event["event"] == "money.updated"
    assert event["data"]["totals"]["rates_missing"] == []
    assert event["data"]["totals"]["quote_cur"] is not None

    # снять ставку УП, вернуть рубли: курс 1, ставка УП снова «не задана»
    back = await s.moderator.put(
        url, json={"currency": "RUB", "rates": [{"discipline_id": None, "rate_rub": None}]}
    )
    assert back.status_code == 200, back.text
    assert (back.json()["exchange_rate"], back.json()["rates_missing"]) == ("1", ["pm"])

    # ничего не изменилось — аудита нет
    same = await s.moderator.put(url, json={"currency": "RUB"})
    assert same.status_code == 200
    assert len(await _audit(db_session, s.pid)) == 2


@pytest.mark.spec("FR-PRJ-01")
async def test_put_money_validation(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/money"
    other = uuid.uuid4()

    async def code(body: dict) -> tuple[int, str]:
        r = await s.moderator.put(url, json=body)
        return r.status_code, r.json().get("code")

    assert await code({"rates": [{"discipline_id": str(s.backend), "rate_rub": "1000001"}]}) == (
        422,
        "VALUE_OUT_OF_RANGE",
    )
    assert await code({"rates": [{"discipline_id": str(other), "rate_rub": "1"}]}) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code({"currency": "XXX", "exchange_rate": "2"}) == (422, "VALIDATION_FAILED")
    assert await code({"currency": "USD"}) == (422, "VALIDATION_FAILED")  # курс обязателен
    assert await code({"currency": "USD", "exchange_rate": "0"}) == (422, "VALUE_OUT_OF_RANGE")
    assert await code({"currency": "USD", "exchange_rate": "1.00001"}) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code({"vat_rate_id": str(other)}) == (422, "VALIDATION_FAILED")
    dup = {"discipline_id": None, "rate_rub": "1"}
    assert await code({"rates": [dup, dup]}) == (422, "VALIDATION_FAILED")
    assert await _audit(db_session, s.pid) == []
