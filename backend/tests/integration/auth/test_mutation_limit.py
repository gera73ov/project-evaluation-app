"""SEC-WEB-07: не больше 300 изменяющих запросов в минуту на пользователя (SEC-008).

Лимит считают зависимости сессии (``auth/mfa_policy``) для всех изменяющих запросов, кроме
выхода; чтение не учитывается. В тесте лимит уменьшен до трёх, чтобы не слать 300 запросов.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.security.ratelimit.limiter import LIMITS, Limit
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-WEB-07")]

BODY = {"notify_digest": True, "notify_questions": False}


async def test_mutations_limited_per_user(
    api: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(LIMITS, "mutations", Limit("mutations", 3, 60))
    await complete_setup(db_session)
    await set_setting(db_session, "security.mfa_policy", {"user": "optional"})
    user, other = await make_user(db_session), await make_user(db_session)

    async def login(login: str) -> None:
        response = await api.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
        assert response.status_code == 200, response.text

    await login(user.login)
    url = "/api/v1/me/notification-settings"
    for _ in range(3):
        ok = await api.put(url, json=BODY, headers=csrf_headers(api))
        assert ok.status_code == 200, ok.text
    limited = await api.put(url, json=BODY, headers=csrf_headers(api))
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    assert (await api.get(url)).status_code == 200, "чтение лимит не тратит"
    assert (await api.post("/api/v1/auth/logout", headers=csrf_headers(api))).status_code == 204

    await login(other.login)
    other_ok = await api.put(url, json=BODY, headers=csrf_headers(api))
    assert other_ok.status_code == 200, "лимит считается на пользователя"
