"""ADM-008: производственный календарь — загрузка CSV data.gov.ru с предпросмотром, правки года,
удаление, аудит «было → стало», рабочие дни по календарю (7.5, BR-PRJ-08, Q-43, GAP-03)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import calendar
from estimator.db.enums import SystemRole
from tests.integration.core.conftest import World
from tests.support.calendar_csv import csv_2024_2025

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5"), pytest.mark.spec("GAP-03")]


async def _audit(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = 'dict.changed' ORDER BY id")
    )
    return [r[0] for r in rows.all() if r[0].get("dictionary") == "calendar"]


def _files(raw: bytes, name: str = "calendar.csv") -> dict[str, Any]:
    return {"file": (name, raw, "text/csv")}


async def test_upload_preview_then_save(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    preview = await admin.post("/admin/calendar", files=_files(csv_2024_2025()))
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["year"], body["saved"]) == (2025, False)  # из нескольких лет — самый поздний
    november = body["months"][10]
    assert november["working_weekends"] == ["2025-11-01"]
    assert "2025-11-03" in november["non_working"]
    assert "2025-11-04" in november["non_working"]
    assert body["months"][0]["working_days"] == 17
    assert (await admin.get("/admin/calendar")).json() == {"items": []}

    saved = await admin.post(
        "/admin/calendar", files=_files(csv_2024_2025()), data={"dry_run": "false"}
    )
    assert saved.json()["saved"] is True
    listed = (await admin.get("/admin/calendar?year=2025")).json()["items"]
    assert len(listed) == 1
    days = {d["date"]: d["is_working"] for d in listed[0]["days"]}
    assert len(days) == 365
    assert days["2025-11-01"] is True
    assert days["2025-01-02"] is False
    assert days["2025-03-07"] is True
    [entry] = await _audit(db_session)
    assert entry["op"] == "import"
    assert entry["changes"]["2025-11-01"] == [False, True]
    assert entry["changes"]["2025-01-02"] == [True, False]

    # рабочие дни по календарю и без него (Q-43)
    assert await calendar.working_days(db_session, dt.date(2025, 10, 31), dt.date(2025, 11, 5)) == 2
    assert await calendar.working_days(db_session, dt.date(2026, 1, 1), dt.date(2026, 1, 9)) == 6


async def test_put_and_delete_year(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    days = [{"date": "2027-01-04", "is_working": False}, {"date": "2027-01-09", "is_working": True}]
    response = await admin.put("/admin/calendar/2027", json={"year": 2027, "days": days})
    assert response.status_code == 200, response.text
    by_date = {d["date"]: d["is_working"] for d in response.json()["days"]}
    assert by_date["2027-01-04"] is False
    assert by_date["2027-01-09"] is True
    assert by_date["2027-01-05"] is True  # не указанный день — по Пн–Пт
    [entry] = await _audit(db_session)
    assert entry["changes"] == {"2027-01-04": [True, False], "2027-01-09": [False, True]}

    mismatch = await admin.put("/admin/calendar/2027", json={"year": 2026, "days": []})
    assert (mismatch.status_code, mismatch.json()["code"]) == (422, "VALIDATION_FAILED")
    alien = await admin.put(
        "/admin/calendar/2027",
        json={"year": 2027, "days": [{"date": "2026-01-01", "is_working": True}]},
    )
    assert alien.status_code == 422

    assert (await admin.delete("/admin/calendar/2027")).status_code == 204
    assert (await admin.get("/admin/calendar?year=2027")).json() == {"items": []}
    assert [e["op"] for e in await _audit(db_session)] == ["update", "delete"]
    assert (await admin.delete("/admin/calendar/2027")).status_code == 204  # повтор — без аудита
    assert len(await _audit(db_session)) == 2


async def test_upload_errors_and_rights(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    bad = await admin.post(
        "/admin/calendar", files=_files(b"\xd0\x9f\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82")
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "VALIDATION_FAILED")
    wrong_day = 'Год/Месяц,1,2,3,4,5,6,7,8,9,10,11,12\n2025,"1,2,40",,,,,,,,,,,\n'
    broken = await admin.post("/admin/calendar", files=_files(wrong_day.encode()))
    assert broken.status_code == 422
    assert "дня 40" in broken.json()["detail"]
    big = await admin.post("/admin/calendar", files=_files(b"x" * (256 * 1024 + 1)))
    assert (big.status_code, big.json()["code"]) == (413, "PAYLOAD_TOO_LARGE")

    moderator = await world.actor(SystemRole.MODERATOR)
    assert (
        await moderator.post("/admin/calendar", files=_files(csv_2024_2025()))
    ).status_code == 403
    assert (
        await moderator.put("/admin/calendar/2027", json={"year": 2027, "days": []})
    ).status_code == 403
    assert (
        await moderator.get("/admin/calendar")
    ).status_code == 200  # dict.read — всем, кроме СА и аудитора
