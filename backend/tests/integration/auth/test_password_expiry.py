"""Истёкший пароль при входе (FR-AUTH-LOC-02, CR-003; решение владельца 06.11.2026).

Вход с истёкшим паролем локальной учётки пускает только к смене пароля: ``step:
"password_change"``, сессия не дольше 15 минут, доступны ``POST /me/password`` и выход, всё
остальное — 403 ``PASSWORD_CHANGE_REQUIRED``. После смены — новая сессия с полным сроком; если
TOTP обязателен и не подключён, дальше действует подключение (R-PRE-MFA).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pyotp
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.sessions import COOKIE_NAME
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.db.enums import SystemRole, UserSource
from estimator.db.models.users import User
from estimator.security.crypto import get_cipher
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-LOC-02")]

NEW = "fresh correct horse 2026"  # nosec B105 — тестовый пароль
ENDPOINT_BLOCKED = ("/api/v1/me", "/api/v1/me/sessions", "/api/v1/me/notification-settings")


async def _expired_user(db: AsyncSession, *roles: SystemRole, days: int = 100) -> User:
    await complete_setup(db)
    await set_setting(db, "security.mfa_policy", {"user": "optional"})
    await set_setting(db, "security.password_policy", {"expiry_days": 90})
    user = await make_user(db, *roles)
    user.password_changed_at = datetime.now(UTC) - timedelta(days=days)
    await db.flush()
    return user


async def _login(api: httpx.AsyncClient, login: str) -> httpx.Response:
    response = await api.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


async def _change(api: httpx.AsyncClient, new: str = NEW) -> httpx.Response:
    return await api.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": new},
        headers=csrf_headers(api),
    )


async def test_expired_password_allows_only_change(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _expired_user(db_session)
    response = await _login(api, user.login)
    assert response.json()["step"] == "password_change"
    assert response.json()["expires_in"] <= 15 * 60
    restricted = api.cookies.get(COOKIE_NAME)
    assert restricted

    for path in ENDPOINT_BLOCKED:
        blocked = await api.get(path)
        assert blocked.status_code == 403, path
        assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED", path
    enroll = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    assert enroll.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    no_csrf = await api.post(
        "/api/v1/me/password", json={"current_password": PASSWORD, "new_password": NEW}
    )
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    wrong = await api.post(
        "/api/v1/me/password",
        json={"current_password": "not the password at all", "new_password": NEW},
        headers=csrf_headers(api),
    )
    assert wrong.json()["code"] == "CURRENT_PASSWORD_INVALID"

    changed = await _change(api)
    assert changed.status_code == 204, changed.text
    assert api.cookies.get(COOKIE_NAME) != restricted, "идентификатор сессии сменился"
    me = await api.get("/api/v1/me")
    assert me.status_code == 200, me.text
    assert me.json()["idle_timeout_seconds"] > 0
    expires = datetime.fromisoformat(me.json()["session_expires_at"])
    assert expires - datetime.now(UTC) > timedelta(hours=1), "полный срок сессии после смены"

    api.cookies.set(COOKIE_NAME, restricted)
    assert (await api.get("/api/v1/me")).status_code == 401, "прежняя сессия закрыта"


async def test_not_expired_or_disabled_logs_in(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    fresh = await _expired_user(db_session, days=10)
    assert (await _login(api, fresh.login)).json()["step"] == "done"
    await set_setting(db_session, "security.password_policy", {"expiry_days": None})
    old = await make_user(db_session)
    old.password_changed_at = datetime.now(UTC) - timedelta(days=3650)
    await db_session.flush()
    assert (await _login(api, old.login)).json()["step"] == "done", "срок по умолчанию не ограничен"


async def test_logout_from_restricted_session(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _expired_user(db_session)
    await _login(api, user.login)
    out = await api.post("/api/v1/auth/logout", headers=csrf_headers(api))
    assert out.status_code == 204
    assert (await api.get("/api/v1/me")).status_code == 401


@pytest.mark.spec("FR-2FA-04")
async def test_password_change_then_forced_enrollment(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _expired_user(db_session, SystemRole.MODERATOR)
    assert (await _login(api, user.login)).json()["step"] == "password_change"
    assert (await _change(api)).status_code == 204
    me = await api.get("/api/v1/me")
    assert me.json()["code"] == "TOTP_ENROLL_REQUIRED", "дальше — обязательное подключение TOTP"
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    assert started.status_code == 200


@pytest.mark.spec("FR-2FA-01")
async def test_expired_after_totp_step(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _expired_user(db_session)
    secret = new_secret()
    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, secret)
    user.totp_enabled = True
    await db_session.flush()
    token = (await _login(api, user.login)).json()["login_token"]
    done = await api.post(
        "/api/v1/auth/totp", json={"login_token": token, "code": pyotp.TOTP(secret).now()}
    )
    assert done.json()["step"] == "password_change"
    assert (await api.get("/api/v1/me")).json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert (await _change(api)).status_code == 204
    me = (await api.get("/api/v1/me")).json()
    assert me["mfa_passed"] is True, "второй фактор, пройденный при входе, сохраняется"


async def test_ad_user_ignores_app_expiry(db_session: AsyncSession) -> None:
    from estimator.auth.login import password_expired

    user = await _expired_user(db_session)
    assert await password_expired(db_session, user)
    user.source = UserSource.AD
    user.password_hash = None
    await db_session.flush()
    assert not await password_expired(db_session, user), "у AD действует политика AD"
