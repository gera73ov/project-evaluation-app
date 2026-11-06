"""AUTH-010: профиль, сессии, TOTP по желанию, резервные коды, настройки уведомлений (/me*)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pyotp
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.sessions import COOKIE_NAME
from estimator.db.enums import SystemRole, UserSource
from estimator.db.models.users import BackupCode, User
from tests.integration.auth.conftest import Clock, complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("15.2")]


async def _login(api: httpx.AsyncClient, login: str, ua: str = "pytest") -> httpx.Response:
    response = await api.post(
        "/api/v1/auth/login",
        json={"login": login, "password": PASSWORD},
        headers={"User-Agent": ua},
    )
    assert response.status_code == 200, response.text
    return response


async def _audit(db: AsyncSession, event: str, user_id: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = :e AND user_id = :u ORDER BY id"
        ),
        {"e": event, "u": user_id},
    )
    return [r[0] for r in rows.all()]


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    await complete_setup(db_session)
    await set_setting(db_session, "security.mfa_policy", {"user": "optional"})
    return await make_user(db_session)


@pytest.mark.spec("8.1")
@pytest.mark.spec("FR-UI-02")
async def test_me_and_patch(api: httpx.AsyncClient, user: User, db_session: AsyncSession) -> None:
    await _login(api, user.login)
    me = (await api.get("/api/v1/me")).json()
    assert me["login"] == user.login
    assert me["source"] == "local"
    assert me["auth_mode"] == "app"
    assert (me["totp_enabled"], me["totp_required"], me["mfa_passed"]) == (False, False, False)
    assert me["system_roles"] == []
    assert me["idle_timeout_seconds"] > 0

    patched = await api.patch(
        "/api/v1/me",
        json={"full_name": "Иван Иванов", "timezone": "Europe/Moscow"},
        headers=csrf_headers(api),
    )
    assert patched.status_code == 200
    assert (patched.json()["full_name"], patched.json()["timezone"]) == (
        "Иван Иванов",
        "Europe/Moscow",
    )
    cleared = await api.patch("/api/v1/me", json={"timezone": None}, headers=csrf_headers(api))
    assert cleared.json()["timezone"] is None
    assert cleared.json()["full_name"] == "Иван Иванов"

    bad = await api.patch("/api/v1/me", json={"timezone": "Mars/Base"}, headers=csrf_headers(api))
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["field"] == "/timezone"
    blank = await api.patch("/api/v1/me", json={"full_name": "  "}, headers=csrf_headers(api))
    assert blank.status_code == 422
    assert (
        await api.patch("/api/v1/me", json={"x": 1}, headers=csrf_headers(api))
    ).status_code == 422
    assert (await api.patch("/api/v1/me", json={"full_name": "А"})).status_code == 403  # CSRF

    user.source = UserSource.AD
    user.password_hash = None
    await db_session.flush()
    ad = await api.patch("/api/v1/me", json={"full_name": "Другое"}, headers=csrf_headers(api))
    assert ad.status_code == 403
    assert ad.json()["code"] == "FORBIDDEN"


@pytest.mark.spec("FR-SESS-04")
async def test_sessions_list_and_end(
    api: httpx.AsyncClient, user: User, db_session: AsyncSession, clock: Clock
) -> None:
    await _login(api, user.login, ua="Firefox")
    first = api.cookies.get(COOKIE_NAME)
    for ua in ("Chrome", "Edge"):
        clock.now += 1
        await _login(api, user.login, ua=ua)
    items = (await api.get("/api/v1/me/sessions")).json()["items"]
    assert [i["user_agent"] for i in items] == ["Edge", "Chrome", "Firefox"]
    assert [i["current"] for i in items] == [True, False, False]
    assert all(i["ip"].startswith("10.") for i in items)

    chrome = items[1]["id"]
    assert (await api.delete(f"/api/v1/me/sessions?id={chrome}",
                             headers=csrf_headers(api))).status_code == 204  # fmt: skip
    for unknown in ("00" * 32, "zz"):
        response = await api.delete(f"/api/v1/me/sessions?id={unknown}", headers=csrf_headers(api))
        assert response.status_code == 204
    items = (await api.get("/api/v1/me/sessions")).json()["items"]
    assert [i["user_agent"] for i in items] == ["Edge", "Firefox"]

    assert (await api.delete("/api/v1/me/sessions", headers=csrf_headers(api))).status_code == 204
    assert [i["user_agent"] for i in (await api.get("/api/v1/me/sessions")).json()["items"]] == [
        "Edge"
    ]
    current = api.cookies.get(COOKIE_NAME)
    api.cookies.set(COOKIE_NAME, first or "")
    assert (await api.get("/api/v1/me")).status_code == 401
    api.cookies.set(COOKIE_NAME, current or "")

    own = (await api.get("/api/v1/me/sessions")).json()["items"][0]["id"]
    response = await api.delete(f"/api/v1/me/sessions?id={own}", headers=csrf_headers(api))
    assert response.status_code == 204
    assert "__Host-session" in response.headers.get("set-cookie", "")
    api.cookies.set(COOKIE_NAME, current or "")
    assert (await api.get("/api/v1/me")).status_code == 401
    details = await _audit(db_session, "auth.sessions.terminated", user.id)
    assert details == [{"count": 1, "reason": "self"}, {"count": 1, "reason": "self"},
                       {"count": 1, "reason": "self"}]  # fmt: skip


@pytest.mark.spec("FR-2FA-01")
@pytest.mark.spec("FR-2FA-02")
async def test_optional_totp_lifecycle(
    api: httpx.AsyncClient, user: User, db_session: AsyncSession, redis_client: Redis
) -> None:
    await _login(api, user.login)
    assert (await api.post("/api/v1/me/backup-codes",
                           headers=csrf_headers(api))).json()["code"] == (
        "TOTP_ENROLL_REQUIRED"
    )  # fmt: skip
    started = await api.post("/api/v1/me/totp", json={}, headers=csrf_headers(api))
    assert started.status_code == 200
    secret = started.json()["secret"]
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/")
    confirmed = await api.post(
        "/api/v1/me/totp", json={"code": pyotp.TOTP(secret).now()}, headers=csrf_headers(api)
    )
    assert confirmed.status_code == 200
    assert len(confirmed.json()["backup_codes"]) == 10
    me = (await api.get("/api/v1/me")).json()
    assert (me["totp_enabled"], me["mfa_passed"]) == (True, True)
    again = await api.post("/api/v1/me/totp", json={}, headers=csrf_headers(api))
    assert again.status_code == 403

    codes = await api.post("/api/v1/me/backup-codes", headers=csrf_headers(api))
    assert codes.status_code == 200
    assert codes.json()["backup_codes"] != confirmed.json()["backup_codes"]
    assert len(await _audit(db_session, "auth.mfa.backup_codes_regenerated", user.id)) == 1

    denied = await api.delete("/api/v1/me/totp", headers=csrf_headers(api))
    assert (denied.status_code, denied.json()["code"]) == (403, "STEP_UP_REQUIRED")
    await redis_client.delete(f"totp:last:{user.id}")
    step_up = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    assert step_up.status_code == 200
    assert (await api.delete("/api/v1/me/totp", headers=csrf_headers(api))).status_code == 204
    me = (await api.get("/api/v1/me")).json()
    assert (me["totp_enabled"], me["mfa_passed"]) == (False, False)
    left = await db_session.scalar(
        select(func.count()).select_from(BackupCode).where(BackupCode.user_id == user.id)
    )
    assert left == 0
    assert await _audit(db_session, "auth.mfa.disabled", user.id) == [{}]
    assert (await api.delete("/api/v1/me/totp", headers=csrf_headers(api))).status_code == 204


@pytest.mark.spec("FR-2FA-04")
async def test_required_totp_cannot_be_disabled(
    api: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis
) -> None:
    await complete_setup(db_session)
    admin = await make_user(db_session, SystemRole.ADMIN)
    await _login(api, admin.login)  # принудительное подключение
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    secret = started.json()["secret"]
    await api.post("/api/v1/auth/totp/enroll/confirm", json={"code": pyotp.TOTP(secret).now()},
                   headers=csrf_headers(api))  # fmt: skip
    assert (await api.get("/api/v1/me")).json()["totp_required"] is True
    await redis_client.delete(f"totp:last:{admin.id}")
    await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    denied = await api.delete("/api/v1/me/totp", headers=csrf_headers(api))
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")


@pytest.mark.spec("FR-NOTIF-02")
async def test_notification_settings(api: httpx.AsyncClient, user: User) -> None:
    await _login(api, user.login)
    assert (await api.get("/api/v1/me/notification-settings")).json() == {
        "notify_digest": True,
        "notify_questions": True,
    }
    body = {"notify_digest": False, "notify_questions": True}
    put = await api.put("/api/v1/me/notification-settings", json=body, headers=csrf_headers(api))
    assert put.json() == body
    assert (await api.get("/api/v1/me/notification-settings")).json() == body
    partial = await api.put(
        "/api/v1/me/notification-settings", json={"notify_digest": True}, headers=csrf_headers(api)
    )
    assert partial.status_code == 422
