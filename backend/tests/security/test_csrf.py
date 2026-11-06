"""TC-SEC-08 (QA-008): каждый изменяющий маршрут API отклоняет запрос без своего CSRF-токена.

SPEC SEC-WEB-04, TC-SEC-08, CL-05. Маршруты берутся из реестра SEC-005
(:func:`estimator.security.authz.routes.api_routes`) работающего приложения, поэтому новый
маршрут попадает в проверку сам. Для каждого ``POST``/``PUT``/``PATCH``/``DELETE`` с сессией:

* без заголовка ``X-CSRF-Token`` → 403 ``CSRF_FAILED``;
* с токеном другой живой сессии → 403 ``CSRF_FAILED``;
* в ответе-отказе есть заголовки безопасности (CL-05).

Без проверки остаются только маршруты без сессии (``public``, ``token.*``): у них нет токена,
к которому можно привязать запрос; их защищают одноразовые токены и SameSite-cookie.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.auth.conftest import complete_setup, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

from estimator.auth.sessions import COOKIE_NAME
from estimator.security.authz.routes import api_routes, declared
from estimator.security.web.csrf import CSRF_COOKIE, CSRF_HEADER

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tc("TC-SEC-08"),
    pytest.mark.spec("SEC-WEB-04"),
]

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PARAM = re.compile(r"\{[^}]+\}")


def _sessionless(codes: tuple[str, ...]) -> bool:
    return bool(codes) and all(c == "public" or c.startswith("token.") for c in codes)


def mutating_routes(app: Any) -> list[tuple[str, str]]:
    """(метод, путь с подставленными параметрами) для всех изменяющих маршрутов с сессией."""
    out: list[tuple[str, str]] = []
    for route in api_routes(app):
        if _sessionless(declared(route)):
            continue
        path = _PARAM.sub(str(uuid.uuid4()), str(route.path))
        out.extend((method, path) for method in sorted(set(route.methods) & MUTATING))
    return out


async def _login(api: httpx.AsyncClient, login: str) -> tuple[str, str]:
    response = await api.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return api.cookies.get(COOKIE_NAME) or "", api.cookies.get(CSRF_COOKIE) or ""


def _assert_csrf_denied(response: httpx.Response, method: str, path: str) -> None:
    where = f"{method} {path}"
    assert response.status_code == 403, f"{where}: {response.status_code} {response.text}"
    body = response.json()
    # RFC 9457 (API-003): code на верхнем уровне; до API-003 — внутри detail
    code = body.get("code") or (body.get("detail") or {}).get("code")
    assert code == "CSRF_FAILED", where
    assert response.headers.get("x-content-type-options") == "nosniff", where
    assert "no-store" in response.headers.get("cache-control", ""), where


async def test_every_mutating_route_requires_own_csrf_token(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    await set_setting(db_session, "security.mfa_policy", {"user": "optional"})
    other, user = await make_user(db_session), await make_user(db_session)
    _, foreign_token = await _login(api, other.login)
    session, own_token = await _login(api, user.login)
    assert foreign_token
    assert own_token
    assert foreign_token != own_token

    routes = mutating_routes(api.app)  # type: ignore[attr-defined]
    assert len(routes) >= 10, routes  # реестр не пуст: проверка действительно что-то обходит
    for method, path in routes:
        api.cookies.set(COOKIE_NAME, session)
        for headers in ({}, {CSRF_HEADER: foreign_token}, {CSRF_HEADER: ""}):
            response = await api.request(method, path, json={}, headers=headers)
            _assert_csrf_denied(response, method, path)

    # Контроль: со своим токеном тот же запрос проходит проверку CSRF (сессия жива)
    api.cookies.set(COOKIE_NAME, session)
    ok = await api.put(
        "/api/v1/me/notification-settings",
        json={"notify_digest": True, "notify_questions": True},
        headers={CSRF_HEADER: own_token},
    )
    assert ok.status_code == 200, ok.text


def test_sessionless_routes_are_only_public_or_token() -> None:
    assert _sessionless(("public",))
    assert _sessionless(("token.activation", "token.login_step"))
    assert not _sessionless(())
    assert not _sessionless(("public", "authenticated"))
