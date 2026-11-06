"""AUTH-004, AUTH-006, AUTH-007, AUTH-012: вход через API целиком."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pyotp
import pytest
from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.mfa_policy import require_totp
from estimator.auth.sessions import COOKIE_NAME
from estimator.auth.totp import encrypt_secret, new_secret, replace_backup_codes
from estimator.db.enums import SystemRole
from estimator.db.models.users import User
from estimator.security.crypto import get_cipher
from tests.integration.auth.conftest import complete_setup, csrf_headers
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.2")]


async def _login(api: httpx.AsyncClient, login: str, password: str = PASSWORD) -> httpx.Response:
    return await api.post("/api/v1/auth/login", json={"login": login, "password": password})


async def _audit(db: AsyncSession, event: str, login: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = :e AND login = :l ORDER BY id"
        ),
        {"e": event, "l": login},
    )
    return [r[0] for r in rows]


async def _with_totp(db: AsyncSession, user: User) -> str:
    secret = new_secret()
    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, secret)
    user.totp_enabled = True
    await db.flush()
    return secret


@pytest.mark.spec("FR-SA-02")
async def test_setup_gate(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    superadmin = await make_user(db_session, SystemRole.SUPERADMIN)
    response = await _login(api, user.login)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "APP_SETUP_IN_PROGRESS"
    sa = await _login(api, superadmin.login)
    assert sa.status_code == 200
    assert sa.json()["step"] == "enroll", "суперадминистратору TOTP обязателен всегда"
    await complete_setup(db_session)
    ok = await _login(api, user.login)
    assert ok.status_code == 200
    assert ok.json()["step"] == "done"
    assert ok.cookies.get(COOKIE_NAME)


@pytest.mark.spec("FR-AUTH-AD-13")
async def test_uniform_failure_and_audit(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session)
    unknown = f"ghost.{uuid.uuid4().hex[:8]}"
    timings = {}
    bodies = {}
    for name, login, password in (("unknown", unknown, PASSWORD), ("wrong", user.login, "nope")):
        started = time.perf_counter()
        response = await _login(api, login, password)
        timings[name] = time.perf_counter() - started
        assert response.status_code == 401
        bodies[name] = response.json()
    assert (
        bodies["unknown"]
        == bodies["wrong"]
        == {"detail": {"code": "LOGIN_FAILED", "auth_mode": "app"}}
    )
    ratio = max(timings.values()) / min(timings.values())
    assert ratio < 3, f"время ответа выдаёт существование логина: {timings}"
    assert [d["reason"] for d in await _audit(db_session, "auth.login.failed", unknown)] == [
        "user_not_found"
    ]
    assert [d["reason"] for d in await _audit(db_session, "auth.login.failed", user.login)] == [
        "wrong_password"
    ]
    empty = await api.post("/api/v1/auth/login", json={"login": " ", "password": "x"})
    assert empty.json()["detail"]["code"] == "LOGIN_FAILED"


@pytest.mark.spec("FR-LOCK-01")
async def test_pair_locked_after_failures(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session)
    for _ in range(5):
        assert (await _login(api, user.login, "wrong")).status_code == 401
    locked = await _login(api, user.login)
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "LOGIN_LOCKED"
    assert int(locked.headers["Retry-After"]) > 0
    events = await _audit(db_session, "auth.lockout.pair_locked", user.login)
    assert events == [{"failures": 5, "minutes": 15, "actor": "system"}]


@pytest.mark.tc("TC-AUTH-04")
@pytest.mark.spec("FR-2FA-01")
async def test_totp_step_replay_and_backup(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session, SystemRole.MODERATOR)
    secret = await _with_totp(db_session, user)
    backup = await replace_backup_codes(db_session, user.id)

    first = await _login(api, user.login)
    assert first.json()["step"] == "totp"
    assert first.json()["expires_in"] == 300
    assert not first.cookies.get(COOKIE_NAME), "до второго шага сессии нет"
    token = first.json()["login_token"]
    bad = await api.post("/api/v1/auth/totp", json={"login_token": token, "code": "000000"})
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "TOTP_INVALID"
    code = pyotp.TOTP(secret).now()
    done = await api.post("/api/v1/auth/totp", json={"login_token": token, "code": code})
    assert done.status_code == 200
    assert done.json()["step"] == "done"
    assert done.cookies.get(COOKIE_NAME)
    again = await api.post("/api/v1/auth/totp", json={"login_token": token, "code": code})
    assert again.json()["detail"]["code"] == "LOGIN_STEP_EXPIRED", "токен одноразовый"

    token2 = (await _login(api, user.login)).json()["login_token"]
    replay = await api.post("/api/v1/auth/totp", json={"login_token": token2, "code": code})
    assert replay.json()["detail"]["code"] == "TOTP_INVALID", "повтор кода отклоняется"
    ok = await api.post("/api/v1/auth/totp", json={"login_token": token2, "backup_code": backup[0]})
    assert ok.status_code == 200
    token3 = (await _login(api, user.login)).json()["login_token"]
    reused = await api.post(
        "/api/v1/auth/totp", json={"login_token": token3, "backup_code": backup[0]}
    )
    assert reused.status_code == 401, "резервный код действует один раз"
    reasons = [d["reason"] for d in await _audit(db_session, "auth.login.failed", user.login)]
    assert reasons == ["invalid_totp", "invalid_totp", "invalid_backup_code"]
    both = await api.post(
        "/api/v1/auth/totp",
        json={"login_token": token3, "code": "123456", "backup_code": "12345678"},
    )
    assert both.status_code == 422


@pytest.mark.spec("FR-2FA-04")
async def test_forced_enrollment(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session, SystemRole.MODERATOR)
    response = await _login(api, user.login)
    assert response.json()["step"] == "enroll"
    assert response.json()["expires_in"] <= 15 * 60
    old_cookie = api.cookies.get(COOKIE_NAME)
    blocked = await api.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "another long passphrase 7"},
        headers=csrf_headers(api),
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "TOTP_ENROLL_REQUIRED"
    no_csrf = await api.post("/api/v1/auth/totp/enroll")
    assert no_csrf.json()["detail"]["code"] == "CSRF_FAILED"
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    assert started.status_code == 200
    secret = started.json()["secret"]
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/")
    confirm = await api.post(
        "/api/v1/auth/totp/enroll/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(api),
    )
    assert confirm.status_code == 200
    codes = confirm.json()["backup_codes"]
    assert len(codes) == 10
    assert all(len(c) == 8 and c.isdigit() for c in codes)
    assert api.cookies.get(COOKIE_NAME) != old_cookie, "идентификатор сессии сменился"
    await db_session.refresh(user)
    assert user.totp_enabled
    enrolled = await _audit(db_session, "auth.mfa.enrolled", user.login)
    assert enrolled == [{"forced": True}]


@pytest.mark.tc("TC-AUTH-08")
@pytest.mark.spec("FR-2FA-05")
async def test_money_requires_totp_then_step_up(
    api: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis
) -> None:
    app = api.app  # type: ignore[attr-defined]

    @app.get("/api/v1/test-money", dependencies=[Depends(require_totp)])
    async def money() -> dict[str, str]:
        return {"rate": "5000"}

    await complete_setup(db_session)
    user = await make_user(db_session)  # TOTP по желанию: вход без кода
    secret = await _with_totp(db_session, user)
    user.totp_enabled = False
    await db_session.flush()
    assert (await _login(api, user.login)).json()["step"] == "done"
    user.totp_enabled = True
    await db_session.flush()
    denied = await api.get("/api/v1/test-money")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "TOTP_REQUIRED"

    wrong = await api.post(
        "/api/v1/auth/step-up",
        json={"code": "000000", "totp_only": True},
        headers=csrf_headers(api),
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "STEP_UP_FAILED"
    passed = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).now(), "totp_only": True},
        headers=csrf_headers(api),
    )
    assert passed.status_code == 200
    assert passed.json() == {"mfa_passed": True, "step_up_until": None}
    assert (await api.get("/api/v1/test-money")).status_code == 200

    await redis_client.delete(f"totp:last:{user.id}")
    full = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    assert full.status_code == 200
    assert full.json()["step_up_until"] is not None
    purposes = [d["purpose"] for d in await _audit(db_session, "auth.step_up.passed", user.login)]
    assert purposes == ["money_totp", "step_up"]


@pytest.mark.spec("FR-SESS-01")
async def test_logout_requires_csrf_and_kills_cookie(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session)
    await _login(api, user.login)
    session_cookie = api.cookies.get(COOKIE_NAME)
    forged = await api.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert forged.status_code == 403
    assert forged.json()["detail"]["code"] == "CSRF_FAILED"
    assert (await api.post("/api/v1/auth/logout", headers=csrf_headers(api))).status_code == 204
    api.cookies.set(COOKIE_NAME, session_cookie or "")
    again = await api.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "x"})
    assert again.status_code == 401


async def test_options_and_security_headers(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/auth/options")
    assert response.json() == {"auth_mode": "app"}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    error = await api.post("/api/v1/auth/logout")
    assert error.status_code == 401
    assert error.headers["X-Content-Type-Options"] == "nosniff", "заголовки и на ошибках"
    big = await api.post("/api/v1/auth/login", content=b"x" * (1024 * 1024 + 1),
                         headers={"content-type": "application/json"})  # fmt: skip
    assert big.status_code == 413
    assert big.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert big.headers["Referrer-Policy"] == "same-origin"
