"""SEC-013: вход и действия суперадминистратора только из разрешённых сетей (FR-SA-06, CL-16).

Тестовый клиент ходит с адреса ``10.x.x.x`` (фикстура ``api``). «Чужая» сеть — 192.168.0.0/16:
зарезервированный логин получает 404, а не 403, отказ пишется в аудит. Обычных пользователей
список не касается.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pyotp
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SA-06")]

FOREIGN = ["192.168.0.0/16"]
OWN = ["10.0.0.0/8"]


async def _login(api: httpx.AsyncClient, login: str) -> httpx.Response:
    return await api.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})


async def _denied(db: AsyncSession, login: str | None = None) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'security.network_denied' "
            "AND (CAST(:l AS text) IS NULL OR login = :l) ORDER BY id"
        ),
        {"l": login},
    )
    return [r[0] for r in rows]


def _not_found(response: httpx.Response) -> bool:
    return response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


@pytest.mark.spec("SEC-AUTH-07")
async def test_superadmin_login_from_foreign_network_is_404(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    sa = await make_user(db_session, SystemRole.SUPERADMIN)
    user = await make_user(db_session, SystemRole.MODERATOR)
    await set_setting(db_session, "security.admin_networks", FOREIGN)

    denied = await _login(api, sa.login)
    assert _not_found(denied), denied.text
    assert "login_token" not in denied.json()
    assert await _denied(db_session, sa.login) == [{"route": "/auth/login"}]
    assert (await _login(api, user.login)).status_code == 200, "обычных учёток список не касается"

    await set_setting(db_session, "security.admin_networks", OWN)
    allowed = await _login(api, sa.login)
    assert allowed.status_code == 200
    assert allowed.json()["step"] == "enroll"


async def test_wrong_password_is_still_404_for_superadmin(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Сеть проверяется раньше пароля: из чужой сети подбор пароля СА ничего не даёт."""
    await complete_setup(db_session)
    sa = await make_user(db_session, SystemRole.SUPERADMIN)
    await set_setting(db_session, "security.admin_networks", FOREIGN)
    response = await api.post("/api/v1/auth/login", json={"login": sa.login, "password": "nope"})
    assert _not_found(response)


async def test_enrollment_and_totp_step_from_foreign_network(
    api: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis
) -> None:
    await complete_setup(db_session)
    sa = await make_user(db_session, SystemRole.SUPERADMIN)
    await set_setting(db_session, "security.admin_networks", OWN)
    assert (await _login(api, sa.login)).json()["step"] == "enroll"

    await set_setting(db_session, "security.admin_networks", FOREIGN)
    assert _not_found(await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api)))
    await set_setting(db_session, "security.admin_networks", OWN)
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    assert started.status_code == 200
    secret = started.json()["secret"]

    await set_setting(db_session, "security.admin_networks", FOREIGN)
    confirm = await api.post(
        "/api/v1/auth/totp/enroll/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(api),
    )
    assert _not_found(confirm)
    await set_setting(db_session, "security.admin_networks", OWN)
    confirmed = await api.post(
        "/api/v1/auth/totp/enroll/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(api),
    )
    assert confirmed.status_code == 200, confirmed.text
    await redis_client.delete(f"totp:last:{sa.id}")

    await set_setting(db_session, "security.admin_networks", FOREIGN)
    step_up = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    assert _not_found(step_up)

    await set_setting(db_session, "security.admin_networks", OWN)
    token = (await _login(api, sa.login)).json()["login_token"]
    await set_setting(db_session, "security.admin_networks", FOREIGN)
    totp = await api.post(
        "/api/v1/auth/totp", json={"login_token": token, "code": pyotp.TOTP(secret).now()}
    )
    assert _not_found(totp)
    routes = {d["route"] for d in await _denied(db_session, sa.login)}
    assert {"/auth/totp/enroll", "/auth/totp/enroll/confirm", "/auth/step-up", "/auth/totp"} <= (
        routes
    )


async def test_ordinary_step_up_ignores_list(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session, SystemRole.MODERATOR)
    await set_setting(db_session, "security.admin_networks", FOREIGN)
    assert (await _login(api, user.login)).json()["step"] == "enroll"
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    assert started.status_code == 200
