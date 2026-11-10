"""SEC-015: просмотр журнала аудита (SEC-AUD-06, Q-27, ``GET /system/audit``)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.security import audit
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-06")]


async def _sign_in(api: httpx.AsyncClient, db: AsyncSession, role: SystemRole) -> str:
    """Вошедший пользователь с ролью ``role`` и подключённым TOTP; возвращает логин."""
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
    return user.login


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
