"""CORE-029 «Результат пресейла» и CORE-032 журнал проекта: права, проверки, сумма договора через
сервис денег, журнал без денег для ролей без ``money.read``, пагинация курсором."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.dictionaries import LossReason
from estimator.realtime.bus.memory import InMemoryBus
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.helpers import audit_details
from tests.integration.core.test_nodes_api import Setup, _setup

pytestmark = [pytest.mark.integration]


async def _reason(db: AsyncSession, name: str) -> uuid.UUID:
    return (await db.scalars(select(LossReason.id).where(LossReason.name == name))).one()


async def _with_presale(world: World, s: Setup) -> Actor:
    presale = await world.actor(SystemRole.PRESALE)
    members = (await s.moderator.get(f"/projects/{s.pid}/members")).json()["items"]
    body = [
        {"user_id": m["user"]["id"], "role": m["role"]}
        | ({"discipline_id": m["discipline_id"]} if m.get("discipline_id") else {})
        for m in members
    ]
    put = await s.moderator.put(
        f"/projects/{s.pid}/members",
        json={"members": [*body, {"user_id": str(presale.id), "role": "presale"}]},
    )
    assert put.status_code == 200, put.text
    return presale


@pytest.mark.spec("BR-PRJ-05")
async def test_outcome_read_and_write(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/outcome"
    initial = (await s.moderator.get(url)).json()
    assert initial == {
        "outcome": "unknown",
        "loss_reason_id": None,
        "loss_reason_text": None,
        "money": {"contract_amount": None},
    }
    # эксперт видит результат без суммы и править не может
    assert "money" not in (await s.backend_expert.get(url)).json()
    denied = await s.backend_expert.put(url, json={"outcome": "won"})
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")

    won = await s.moderator.put(url, json={"outcome": "won", "contract_amount": "1500000"})
    assert won.status_code == 200, won.text
    assert won.json() == {
        "outcome": "won",
        "loss_reason_id": None,
        "loss_reason_text": None,
        "money": {"contract_amount": "1500000"},
    }
    assert (await s.backend_expert.get(url)).json()["outcome"] == "won"
    [details] = await audit_details(db_session, "project.money.changed", s.pid)
    assert details["fields"] == ["contract_amount"]

    await deliver_events(db_session)
    [updated] = [e for e in events.on(f"project:{s.pid}") if e["event"] == "project.updated"][-1:]
    assert updated["data"]["changes"] == {"outcome": "won"}
    [money_event] = events.on(f"project:{s.pid}:money")
    assert money_event["data"]["contract_amount"] == "1500000"

    # пресейл проекта меняет результат, сумму не трогает (у него нет money.write)
    presale = await _with_presale(world, s)
    price = await _reason(db_session, "Цена")
    lost = await presale.put(url, json={"outcome": "lost", "loss_reason_id": str(price)})
    assert lost.status_code == 200, lost.text
    assert lost.json()["loss_reason_id"] == str(price)
    assert lost.json()["money"] == {"contract_amount": "1500000"}
    no_money = await presale.put(url, json={"outcome": "won", "contract_amount": "1"})
    assert (no_money.status_code, no_money.json()["code"]) == (403, "FORBIDDEN")

    # руководитель пресейла правит результат любого проекта
    head = await world.actor(SystemRole.PRESALE_HEAD)
    other = await _reason(db_session, "Другое")
    by_head = await head.put(
        url,
        json={
            "outcome": "lost",
            "loss_reason_id": str(other),
            "loss_reason_text": " Ушли в облако ",
        },
    )
    assert by_head.status_code == 200, by_head.text
    assert by_head.json()["loss_reason_text"] == "Ушли в облако"

    # другой результат очищает причину
    cancelled = await s.moderator.put(url, json={"outcome": "cancelled"})
    assert cancelled.json()["loss_reason_id"] is None
    assert cancelled.json()["loss_reason_text"] is None


@pytest.mark.spec("BR-PRJ-05")
async def test_outcome_validation(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/outcome"
    other = await _reason(db_session, "Другое")

    async def code(body: dict) -> tuple[int, str]:
        r = await s.moderator.put(url, json=body)
        return r.status_code, r.json().get("code")

    assert await code({"outcome": "lost"}) == (422, "VALIDATION_FAILED")
    assert await code({"outcome": "lost", "loss_reason_id": str(uuid.uuid4())}) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code({"outcome": "lost", "loss_reason_id": str(other)}) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code({"outcome": "lost", "contract_amount": "10"}) == (422, "VALIDATION_FAILED")
    assert await code({"outcome": "won", "contract_amount": "-1"}) == (422, "VALIDATION_FAILED")
    assert await code({"outcome": "won", "contract_amount": "1" * 21}) == (
        422,
        "VALUE_OUT_OF_RANGE",
    )
    assert await code({"outcome": "maybe"}) == (422, "VALIDATION_FAILED")
    no_totp = await world.session_for(s.moderator.id, SystemRole.MODERATOR, mfa=False)
    blocked = await no_totp.put(url, json={"outcome": "won", "contract_amount": "5"})
    assert (blocked.status_code, blocked.json()["code"]) == (403, "TOTP_REQUIRED")
    # без суммы TOTP не нужен
    assert (await no_totp.put(url, json={"outcome": "won"})).status_code == 200


@pytest.mark.spec("BR-PRJ-05")
async def test_outcome_in_completed_project(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    for to in ("consolidation", "completed"):
        moved = await s.moderator.post(f"/projects/{s.pid}/status", json={"to": to})
        assert moved.status_code == 200, moved.text
    won = await s.moderator.put(f"/projects/{s.pid}/outcome", json={"outcome": "won"})
    assert won.status_code == 200, won.text


@pytest.mark.spec("11.6")
async def test_journal(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/journal"
    rates = await s.moderator.put(
        f"/projects/{s.pid}/money",
        json={"rates": [{"discipline_id": str(s.backend), "rate_rub": "3000"}]},
    )
    assert rates.status_code == 200, rates.text
    assert (
        await s.moderator.patch(f"/projects/{s.pid}", json={"duration_weeks": 12})
    ).status_code == 200

    full = (await s.moderator.get(url)).json()
    actions = [e["action"] for e in full["items"]]
    assert actions[0] == "project.settings"
    assert actions[1] == "money.changed"
    assert "project.status" in actions
    assert "team.changed" in actions
    assert actions[-1] == "project.created"
    money_entry = full["items"][1]
    assert money_entry["changes"] == {}
    assert money_entry["money"]["changes"] == {f"rate:{s.backend}": [None, "3000"]}
    assert full["items"][0]["changes"] == {"duration_weeks": [None, 12]}
    assert full["items"][0]["user"]["id"] == str(s.moderator.id)
    assert full["next_cursor"] is None

    # эксперт не видит записей об изменении ставок
    seen = (await s.backend_expert.get(url)).json()["items"]
    assert "money.changed" not in [e["action"] for e in seen]
    assert len(seen) == len(full["items"]) - 1
    assert all("money" not in e for e in seen)

    # страницы по одной записи проходят весь журнал без повторов
    ids: list[str] = []
    cursor: str | None = None
    while True:
        params: dict = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        page = (await s.moderator.get(url, params=params)).json()
        ids += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert ids == [e["id"] for e in full["items"]]

    bad = await s.moderator.get(url, params={"cursor": "garbage"})
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")


@pytest.mark.spec("11.6")
async def test_journal_outcome_entries(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    price = await _reason(db_session, "Цена")
    url = f"/projects/{s.pid}/outcome"
    assert (
        await s.moderator.put(url, json={"outcome": "won", "contract_amount": "900"})
    ).status_code == 200
    assert (
        await s.moderator.put(url, json={"outcome": "lost", "loss_reason_id": str(price)})
    ).status_code == 200
    items = (await s.moderator.get(f"/projects/{s.pid}/journal")).json()["items"]
    assert items[0]["action"] == "outcome.changed"
    assert items[0]["changes"] == {"outcome": ["won", "lost"], "loss_reason": [None, "Цена"]}
    assert items[1]["money"]["changes"] == {"contract_amount": [None, "900"]}
    assert items[2]["changes"] == {"outcome": ["unknown", "won"]}
    expert = (await s.backend_expert.get(f"/projects/{s.pid}/journal")).json()["items"]
    assert [e["action"] for e in expert[:2]] == ["outcome.changed", "outcome.changed"]
