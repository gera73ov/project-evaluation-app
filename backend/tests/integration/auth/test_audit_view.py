"""SEC-015: просмотр журнала аудита (SEC-AUD-06, Q-27, ``GET /system/audit``)."""

from __future__ import annotations

import csv
import io
import time
import uuid
from typing import Any

import httpx
import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.session import run_after_commit
from estimator.exports import engine
from estimator.security import audit
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-06")]


async def _sign_in(api: httpx.AsyncClient, db: AsyncSession, role: SystemRole) -> str:
    """Вошедший пользователь с ролью ``role`` и подключённым TOTP; возвращает логин."""
    return (await _sign_in_with_secret(api, db, role))[0]


async def _sign_in_with_secret(
    api: httpx.AsyncClient, db: AsyncSession, role: SystemRole
) -> tuple[str, str]:
    await complete_setup(db)
    await set_setting(db, "security.admin_networks", [])
    user = await make_user(db, role)
    login = await api.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
    assert login.status_code == 200, login.text
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    confirmed = await api.post(
        "/api/v1/auth/totp/enroll/confirm",
        json={"code": pyotp.TOTP(started.json()["secret"]).now()},
        headers=csrf_headers(api),
    )
    assert confirmed.status_code == 200, confirmed.text
    return user.login, started.json()["secret"]


async def _seed(db: AsyncSession, mark: str) -> None:
    """По событию в категориях «Система», «Справочники», «Пользователи и роли», «Вход»."""
    for event, details in (
        ("system.settings.changed", {"section": "smtp", "changes": {}}),
        ("dict.changed", {"dictionary": "tags", "op": "created", "changes": {}}),
        ("users.blocked", {"block_reason": "manual"}),
        ("auth.login.failed", {"reason": "wrong_password"}),
    ):
        await audit.write(db, event, "success" if event != "auth.login.failed" else "failure",
                          login=mark, details=details, actor="anonymous")  # fmt: skip


async def _page(api: httpx.AsyncClient, **params: Any) -> httpx.Response:
    return await api.get("/api/v1/system/audit", params=params)


async def _viewed(db: AsyncSession, login: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'audit.viewed' AND login = :l "
            "ORDER BY id"
        ),
        {"l": login},
    )
    return [r[0] for r in rows]


@pytest.mark.parametrize("role", [SystemRole.SUPERADMIN, SystemRole.SECURITY_AUDITOR])
async def test_full_journal(api: httpx.AsyncClient, db_session: AsyncSession,
                            role: SystemRole) -> None:  # fmt: skip
    me = await _sign_in(api, db_session, role)
    mark = f"m.{uuid.uuid4().hex[:8]}"
    await _seed(db_session, mark)
    response = await _page(api, limit=200)
    assert response.status_code == 200, response.text
    mine = [i for i in response.json()["items"] if i["login"] == mark]
    assert [i["category"] for i in mine] == ["auth", "users_roles", "dictionaries", "system"]
    assert mine[0]["result"] == "failure"
    ids = [i["id"] for i in response.json()["items"]]
    assert ids == sorted(ids, reverse=True), "от новых к старым"
    assert await _viewed(db_session, me) == [{"filters": {}}]


@pytest.mark.spec("Q-27")
async def test_admin_sees_only_dictionaries_and_users(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    me = await _sign_in(api, db_session, SystemRole.ADMIN)
    mark = f"m.{uuid.uuid4().hex[:8]}"
    await _seed(db_session, mark)
    response = await _page(api, limit=200)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {i["category"] for i in items} <= {"dictionaries", "users_roles"}
    assert [i["event_type"] for i in items if i["login"] == mark] == ["users.blocked",
                                                                      "dict.changed"]  # fmt: skip
    hidden = await _page(api, event_type="system.settings.changed")
    assert hidden.json()["items"] == [], "фильтр по типу не открывает чужие категории"
    assert await _viewed(db_session, me) == [
        {"filters": {"category": ["dictionaries", "users_roles"]}},
        {"filters": {"type": "system.settings.changed",
                     "category": ["dictionaries", "users_roles"]}},
    ]  # fmt: skip


async def test_filters_and_cursor(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    me = await _sign_in(api, db_session, SystemRole.SECURITY_AUDITOR)
    mark = f"m.{uuid.uuid4().hex[:8]}"
    await _seed(db_session, mark)
    await _seed(db_session, mark)
    failures = await _page(api, result="failure", event_type="auth.login.failed", limit=200)
    assert all(i["result"] == "failure" for i in failures.json()["items"])
    assert sum(i["login"] == mark for i in failures.json()["items"]) == 2

    now = await db_session.scalar(text("SELECT now()"))
    later = await _page(api, **{"from": (now.replace(year=now.year + 1)).isoformat()})
    assert later.json() == {"items": [], "next_cursor": None}

    first = await _page(api, event_type="dict.changed", limit=1)
    assert first.json()["items"][0]["login"] == mark
    cursor = first.json()["next_cursor"]
    assert cursor
    second = await _page(api, event_type="dict.changed", limit=1, cursor=cursor)
    assert second.json()["items"][0]["id"] < first.json()["items"][0]["id"]
    assert second.json()["items"][0]["login"] == mark
    viewed = await _viewed(db_session, me)
    assert len(viewed) == 3, "листание по курсору в аудит не пишется"
    assert viewed[0]["filters"] == {"type": "auth.login.failed", "result": "failure"}
    assert viewed[1]["filters"]["period"][1] is None

    bad = await _page(api, cursor="forged")
    assert bad.status_code == 400


@pytest.mark.parametrize("role", [SystemRole.MODERATOR, SystemRole.PRESALE])
async def test_other_roles_forbidden(api: httpx.AsyncClient, db_session: AsyncSession,
                                     role: SystemRole) -> None:  # fmt: skip
    await _sign_in(api, db_session, role)
    response = await _page(api)
    assert response.status_code == 403


# --- выгрузка CSV (SEC-015, FR-EXP-06) ---------------------------------------------------------


async def _export(api: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await api.post("/api/v1/system/audit/export", json=body, headers=csrf_headers(api))


@pytest.mark.spec("FR-EXP-06")
async def test_export_csv(
    api: httpx.AsyncClient, db_session: AsyncSession, redis_client: Any, export_queue: list[Any]
) -> None:
    me, secret = await _sign_in_with_secret(api, db_session, SystemRole.SECURITY_AUDITOR)
    mark = f"m.{uuid.uuid4().hex[:8]}"
    await _seed(db_session, mark)
    await audit.write(db_session, "auth.login.failed", "failure", login="=cmd|calc",
                      details={"reason": "wrong_password"}, actor="anonymous")  # fmt: skip
    now = await db_session.scalar(text("SELECT now()"))
    period = {"from": now.replace(year=now.year - 1).isoformat(),
              "to": now.replace(year=now.year + 1).isoformat()}  # fmt: skip

    no_step_up = await _export(api, **period)
    assert no_step_up.status_code == 403
    assert no_step_up.json()["code"] == "STEP_UP_REQUIRED"
    await redis_client.delete(f"totp:last:{(await _user_id(db_session, me))}")
    stepped = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    assert stepped.status_code == 200, stepped.text
    reversed_period = await _export(api, **{"from": period["to"], "to": period["from"]})
    assert reversed_period.status_code == 422

    made = await _export(api, **period, event_type="dict.changed")
    assert made.status_code == 202, made.text
    assert made.json()["kind"] == "audit_csv"
    await db_session.commit()
    await run_after_commit(db_session)
    [job] = [j for j in export_queue if str(j.export_id) == made.json()["id"]]
    await engine.run(db_session, job)
    ready = (await api.get(f"/api/v1/exports/{job.export_id}")).json()
    assert ready["status"] == "ready"
    assert ready["file_name"].startswith("Аудит_")
    assert ready["file_name"].endswith(".csv")
    got = await api.get(ready["download_url"])
    assert got.status_code == 200
    raw = got.content.decode("utf-8")
    assert raw.startswith("\ufeff# Коммерческая тайна; ")
    lines = list(csv.reader(io.StringIO(raw.lstrip("\ufeff")), delimiter=";"))
    assert lines[1][:4] == ["time", "type", "category", "result"]
    data = [r for r in lines[2:] if r]
    assert {r[1] for r in data} == {"dict.changed"}
    assert any(r[5] == mark for r in data)
    assert all(len(r[13]) == 64 for r in data), "hash каждой записи"

    everything = await _export(api, **period, result="failure")
    await db_session.commit()
    await run_after_commit(db_session)
    [job2] = [j for j in export_queue if str(j.export_id) == everything.json()["id"]]
    await engine.run(db_session, job2)
    body = (await api.get(f"/api/v1/exports/{job2.export_id}/download")).content.decode()
    assert ";'=cmd|calc;" in body, "формульный префикс экранирован"

    exported = await db_session.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = 'audit.exported' "
             "AND login = :l ORDER BY id"), {"l": me},
    )  # fmt: skip
    first = exported.scalars().first()
    assert first["filters"]["type"] == "dict.changed"
    assert first["rows"] == len(data)


async def _user_id(db: AsyncSession, login: str) -> Any:
    return await db.scalar(text("SELECT id FROM users WHERE login = :l"), {"l": login})


async def test_admin_cannot_export(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _sign_in(api, db_session, SystemRole.ADMIN)
    response = await _export(api, **{"from": "2026-01-01T00:00:00Z", "to": "2026-12-31T00:00:00Z"})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
