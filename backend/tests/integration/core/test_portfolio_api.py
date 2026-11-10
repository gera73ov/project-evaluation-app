"""CORE-070: портфель руководителя пресейла — реестр с деньгами и фильтрами, сводка за период,
аудит первого открытия чужого проекта за сессию (FR-PORT-01, FR-PORT-02, GAP-05, R-02,
TC-PORT-01)."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.dictionaries import LossReason
from estimator.db.models.files import Snapshot
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import audit_details, create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PORT-01"), pytest.mark.spec("10.4")]

DAY = dt.datetime(2001, 3, 10, 9, 0, tzinfo=dt.UTC)


async def _project(
    world: World, moderator: Actor, db: AsyncSession, name: str, **kw: Any
) -> uuid.UUID:
    pid = await create_project(world, moderator)
    sets = ", ".join(f"{k} = :{k}" for k in ("name", *kw))
    sql = f"UPDATE projects SET {sets} WHERE id = :id"  # noqa: S608 — имена столбцов из теста
    await db.execute(text(sql), {"id": pid, "name": name, **kw})
    return pid


async def _money(
    db: AsyncSession, pid: uuid.UUID, *, quote_rub: int, quote_cur: int, contract: int | None = None
) -> None:
    await db.execute(
        text(
            "INSERT INTO project_totals (project_id, e, p80, p90, cost_rub, quote_rub, quote_cur,"
            " rates_missing, project_version, updated_at) VALUES (:p, 100, 120, 130, :c, :r, :q,"
            " false, 1, now())"
        ),
        {"p": pid, "c": quote_rub - 1, "r": quote_rub, "q": quote_cur},
    )
    await db.execute(
        text("UPDATE project_money SET contract_amount = :a WHERE project_id = :p"),
        {"a": contract, "p": pid},
    )


async def test_registry(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    presale = await world.actor(SystemRole.PRESALE)
    tag = uuid.uuid4().hex[:8]
    first = await _project(world, moderator, db_session, f"Реестр {tag} А")
    await moderator.put(
        f"/projects/{first}/members",
        json={"members": [{"user_id": str(moderator.id), "role": "moderator"},
                          {"user_id": str(presale.id), "role": "presale"}]},
    )  # fmt: skip
    await _money(db_session, first, quote_rub=1_000_000, quote_cur=1_000_000)
    second = await _project(world, moderator, db_session, f"Реестр {tag} Б", status="archived")
    head = await world.actor(SystemRole.PRESALE_HEAD)

    page = await head.get("/portfolio/projects", params={"q": tag, "limit": 1})
    assert page.status_code == 200, page.text
    [item] = page.json()["items"]
    assert item["id"] == str(second)  # от новых к старым; архив тоже в реестре
    empty = dict.fromkeys(("quote_cur", "quote_rub", "cost_rub", "contract_amount"))
    assert item["money"] == {"currency": "RUB", "rates_missing": False, **empty}
    rest = await head.get(
        "/portfolio/projects", params={"q": tag, "cursor": page.json()["next_cursor"]}
    )
    [row] = rest.json()["items"]
    assert rest.json()["next_cursor"] is None
    assert (row["id"], row["quote_figure"], row["quote_hours"]) == (str(first), "p80", "120.00")
    assert [m["id"] for m in row["moderators"]] == [str(moderator.id)]
    assert [p["id"] for p in row["presales"]] == [str(presale.id)]
    assert (row["money"]["quote_rub"], row["money"]["cost_rub"]) == ("1000000", "999999")
    assert row["no_moderator"] is False

    archived = await head.get("/portfolio/projects", params={"q": tag, "status": "archived"})
    assert [i["id"] for i in archived.json()["items"]] == [str(second)]
    other = await world.actor(SystemRole.MODERATOR)
    by_moderator = await head.get(
        "/portfolio/projects", params={"q": tag, "moderator_id": str(other.id)}
    )
    assert by_moderator.json()["items"] == []
    old = await head.get("/portfolio/projects", params={"q": tag, "to": "2001-01-01"})
    assert old.json()["items"] == []

    assert (await moderator.get("/portfolio/projects")).status_code == 403
    no_totp = await world.actor(SystemRole.PRESALE_HEAD, mfa=False)
    assert (await no_totp.get("/portfolio/projects")).status_code == 403
    bad = await head.get("/portfolio/projects", params={"cursor": "x" * 40})
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")


@pytest.mark.spec("R-02")
@pytest.mark.spec("TC-PORT-01")
async def test_first_open_audited_once_per_session(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    head = await world.actor(SystemRole.PRESALE_HEAD)
    for _ in range(2):
        assert (await head.get(f"/projects/{pid}")).status_code == 200
        assert (await head.get(f"/projects/{pid}/money")).status_code == 200
    assert len(await audit_details(db_session, "project.opened_by_presale_head", pid)) == 1


@pytest.mark.spec("FR-PORT-02")
@pytest.mark.spec("GAP-05")
async def test_summary(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    reasons = {r.name: r for r in await db_session.scalars(select(LossReason))}
    other = next(r for r in reasons.values() if r.is_other)
    price = next(r for r in reasons.values() if not r.is_other)
    at = DAY
    won = await _project(world, moderator, db_session, "Сводка выигран", outcome="won",
                         status="completed", created_at=at)  # fmt: skip
    await _money(db_session, won, quote_rub=3_000_000, quote_cur=30_000, contract=27_000)
    won2 = await _project(world, moderator, db_session, "Сводка выигран 2", outcome="won",
                          status="completed", created_at=at)  # fmt: skip
    await _money(db_session, won2, quote_rub=1_000_000, quote_cur=1_000_000, contract=1_000_000)
    lost = await _project(world, moderator, db_session, "Сводка проигран", outcome="lost",
                          loss_reason_id=other.id, loss_reason_text="Ушли к конкуренту",
                          created_at=DAY + dt.timedelta(days=31))  # fmt: skip
    await _money(db_session, lost, quote_rub=4_000_000, quote_cur=4_000_000)
    lost2 = await _project(world, moderator, db_session, "Сводка проигран 2", outcome="lost",
                           loss_reason_id=price.id, created_at=at)  # fmt: skip
    work = await _project(world, moderator, db_session, "Сводка в работе", created_at=at)
    await _money(db_session, work, quote_rub=500_000, quote_cur=500_000)
    for pid, days in ((won, 2), (won2, 4), (lost2, 10)):
        db_session.add(
            Snapshot(
                project_id=pid, name="v1", project_version=1, created_by=moderator.id,
                created_at=DAY + dt.timedelta(days=days), payload={"n": 1},
                payload_sha256=hashlib.sha256(b"x").digest(),
            )
        )  # fmt: skip
    await db_session.flush()

    head = await world.actor(SystemRole.PRESALE_HEAD)
    response = await head.get(
        "/portfolio/summary", params={"from": "2001-03-01", "to": "2001-04-30"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == {"from": "2001-03-01", "to": "2001-04-30"}
    assert body["by_outcome"] == {"unknown": 1, "won": 2, "lost": 2, "cancelled": 0}
    assert body["by_status"]["completed"] == 2
    assert body["by_status"]["preparation"] == 3
    assert body["won_share_count_pct"] == "50"
    assert body["won_share_money_pct"] == "50"  # 4 млн из 8 млн
    assert (body["sum_won_cur"], body["sum_lost_cur"], body["sum_in_progress_cur"]) == (
        "4000000", "4000000", "4500000",
    )  # fmt: skip
    assert body["contract_to_quote_median_pct"] == "95"  # медиана 90% и 100%
    assert body["first_snapshot_median_days"] == "4"
    assert body["by_month"] == [
        {"month": "2001-03", "won": 2, "lost": 1, "cancelled": 0},
        {"month": "2001-04", "won": 0, "lost": 1, "cancelled": 0},
    ]
    by_reason = {r["loss_reason_id"]: r for r in body["loss_reasons"]}
    assert by_reason[str(other.id)]["texts"] == ["Ушли к конкуренту"]
    assert by_reason[str(price.id)] == {"loss_reason_id": str(price.id), "name": price.name,
                                        "count": 1, "texts": []}  # fmt: skip

    empty = await head.get("/portfolio/summary", params={"from": "1990-01-01", "to": "1990-01-31"})
    assert empty.json()["won_share_count_pct"] is None
    period = {"from": "2001-03-01", "to": "2001-03-02"}
    assert (await moderator.get("/portfolio/summary", params=period)).status_code == 403
