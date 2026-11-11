"""CORE-060/061: снимки — создание, список, неизменяемость содержимого, «ошибочный», деньги только
ролям с деньгами; сравнение «снимок ↔ текущее» и «снимок ↔ снимок» (FR-SNAP-01…04, BR-PRJ-02,
TC-SNAP-01)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.files import Snapshot
from estimator.db.models.tree import Node
from tests.integration.core.conftest import World
from tests.integration.core.helpers import audit_details
from tests.integration.core.test_nodes_api import Setup, _patch, _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SNAP-01"), pytest.mark.spec("10.2")]


async def _rates(s: Setup, backend: str, pm: str = "2500") -> None:
    put = await s.moderator.put(
        f"/projects/{s.pid}/money",
        json={"rates": [{"discipline_id": str(s.backend), "rate_rub": backend},
                        {"discipline_id": None, "rate_rub": pm}]},
    )  # fmt: skip
    assert put.status_code == 200, put.text


async def _snapshot(s: Setup, name: str) -> dict[str, Any]:
    created = await s.moderator.post(f"/projects/{s.pid}/snapshots", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()


async def _version(db: AsyncSession, node_id: str) -> int:
    return (await db.scalars(select(Node.version).where(Node.id == node_id))).one()


@pytest.mark.spec("FR-SNAP-02")
@pytest.mark.spec("BR-PRJ-02")
async def test_create_list_and_invalidate(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    await _rates(s, "3000")

    blank = await s.moderator.post(f"/projects/{s.pid}/snapshots", json={"name": "  "})
    assert (blank.status_code, blank.json()["code"]) == (422, "VALIDATION_FAILED")
    v1 = await _snapshot(s, "v1 — КП отправлено")
    assert float(v1["totals"]["e"]) > 0
    assert v1["is_invalid"] is False
    assert v1["money"]["currency"] == "RUB"
    assert v1["money"]["quote_cur"]
    assert v1["created_by"]["id"] == str(s.moderator.id)
    [entry] = await audit_details(db_session, "project.snapshot.created", s.pid)
    stored = await db_session.get(Snapshot, v1["id"])
    assert entry["payload_sha256"] == stored.payload_sha256.hex()
    assert stored.payload["nodes"]
    assert "threads" not in stored.payload

    expert_list = await s.backend_expert.get(f"/projects/{s.pid}/snapshots")
    assert expert_list.status_code == 200, expert_list.text
    assert [i["id"] for i in expert_list.json()["items"]] == [v1["id"]]
    assert "money" not in expert_list.json()["items"][0]  # G-03: эксперт без денег
    assert "money" not in str(expert_list.json())
    assert (await s.backend_expert.post(f"/projects/{s.pid}/snapshots",
                                        json={"name": "x"})).status_code == 403  # fmt: skip

    # переименование фазы в справочнике не меняет снимок
    phase_id = stored.payload["phases"][0]["id"]
    name = stored.payload["phases"][0]["name"]
    await db_session.execute(
        text("UPDATE phases SET name = name || ' (новое)' WHERE id = :id"), {"id": phase_id}
    )
    db_session.expire_all()
    again = await db_session.get(Snapshot, v1["id"])
    assert again.payload["phases"][0]["name"] == name

    assert (await s.backend_expert.post(f"/snapshots/{v1['id']}/invalidate")).status_code == 403
    marked = await s.moderator.post(f"/snapshots/{v1['id']}/invalidate")
    assert marked.status_code == 200, marked.text
    assert marked.json()["is_invalid"] is True
    twice = await s.moderator.post(f"/snapshots/{v1['id']}/invalidate")
    assert (twice.status_code, twice.json()["code"]) == (409, "INVALID_TRANSITION")
    assert len(await audit_details(db_session, "project.snapshot.invalidated", s.pid)) == 1


async def test_not_in_preparation(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session, launch=False)
    early = await s.moderator.post(f"/projects/{s.pid}/snapshots", json={"name": "v0"})
    assert (early.status_code, early.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")


@pytest.mark.spec("FR-SNAP-03")
@pytest.mark.spec("FR-SNAP-04")
@pytest.mark.tc("TC-SNAP-01")
async def test_diff(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    a = await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    b = await _leaf(s.backend_expert, s, branch.id, "Выход", o="1", r="2", p="3")
    await _rates(s, "3000")
    v1 = await _snapshot(s, "v1")

    renamed = await _patch(s.backend_expert, a["id"], await _version(db_session, a["id"]),
                           title="Вход по паролю", o="10")  # fmt: skip
    assert renamed.status_code == 200, renamed.text
    c = await _leaf(s.backend_expert, s, branch.id, "Регистрация", o="4", r="6", p="8")
    assert (await s.backend_expert.delete(f"/nodes/{b['id']}")).status_code == 200
    await _rates(s, "3500")

    current = await s.moderator.get(f"/snapshots/{v1['id']}/diff", params={"with": "current"})
    assert current.status_code == 200, current.text
    body = current.json()
    rows = {r["node_id"]: r for r in body["rows"]}
    assert set(rows) == {a["id"], b["id"], c["id"]}
    assert (rows[a["id"]]["change"], rows[a["id"]]["fields"]) == ("changed", ["title", "o"])
    assert rows[a["id"]]["before"]["o"] == "8"
    assert rows[a["id"]]["after"]["o"] == "10"
    assert rows[b["id"]]["change"] == "removed"
    assert rows[b["id"]]["after"] is None
    assert rows[c["id"]]["change"] == "added"
    assert rows[c["id"]]["before"] is None
    assert rows[c["id"]]["last_changed_by"]["id"] == str(s.backend_expert.id)
    assert body["base"]["label"] == "v1"
    assert body["with"]["snapshot_id"] is None
    delta = sum(float(r["delta_e"]) for r in body["rows"])
    works = float(body["with"]["totals"]["e"]) - float(body["base"]["totals"]["e"])
    assert float(body["totals_delta"]["e"]) == pytest.approx(works)
    assert delta != 0
    assert body["pm"] is not None
    money = body["money"]
    assert money["rates_changed"] is True
    assert int(money["rates_effect_rub"]) > 0
    assert [p["key"] for p in body["params"]] == ["rate"]

    expert = await s.backend_expert.get(f"/snapshots/{v1['id']}/diff", params={"with": "current"})
    assert expert.status_code == 200, expert.text
    assert "money" not in expert.json()
    assert expert.json()["params"] == []

    v2 = await _snapshot(s, "v2")
    await s.moderator.post(f"/snapshots/{v1['id']}/invalidate")  # «ошибочный» тоже сравнивается
    pair = await s.moderator.get(f"/snapshots/{v1['id']}/diff", params={"with": v2["id"]})
    assert pair.status_code == 200, pair.text
    assert {r["node_id"] for r in pair.json()["rows"]} == set(rows)
    assert pair.json()["totals_delta"] == body["totals_delta"]
    same = await s.moderator.get(f"/snapshots/{v2['id']}/diff", params={"with": "current"})
    assert same.json()["rows"] == []
    assert same.json()["pm"] is None

    for bad in ("nope", "00000000-0000-7000-8000-000000000000"):
        missing = await s.moderator.get(f"/snapshots/{v1['id']}/diff", params={"with": bad})
        assert missing.status_code == 404
