"""Реестр маршрутов и правило «запрещено по умолчанию» (SEC-AUTHZ-02, R-DENY-DEFAULT, TC-SEC-01).

Каждый маршрут ``/api/…`` объявляет ``x-permission`` — код или список кодов из каталога
(``openapi_extra`` или ``ApiRouter(permission=…)``). Право должно быть обеспечено зависимостью:

* непсевдоправа — :func:`~estimator.security.authz.deps.gate` с теми же кодами;
* ``authenticated`` — зависимость полной сессии (``ActivePrincipal``);
* ``session.pre_mfa`` — сессия до подключения TOTP (``PreMfaPrincipal``) или полная;
* ``session.password_change`` — сессия с истёкшим паролем (``PasswordChangePrincipal``);
* ``public``, ``token.*`` — без сессии: токен проверяет сам обработчик.

:func:`assert_routes_protected` вызывается в ``create_app``: приложение с незащищённым маршрутом
не стартует, и тест TC-SEC-01 падает.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from estimator.auth import mfa_policy
from estimator.security.authz.catalog import PSEUDO, Catalog, load_catalog

API_PREFIX = "/api/"
_NEEDS = {
    "authenticated": {mfa_policy.active_principal},
    "session.pre_mfa": {
        mfa_policy.pre_mfa_principal,
        mfa_policy.active_principal,
        mfa_policy.any_session_principal,
    },
    "session.password_change": {
        mfa_policy.password_change_principal,
        mfa_policy.any_session_principal,
    },
}


class UnprotectedRouteError(RuntimeError):
    """Маршрут без объявленного или необеспеченного права."""


def _calls(dependant: Dependant) -> Iterator[object]:
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def declared(route: Any) -> tuple[str, ...]:
    raw = (route.openapi_extra or {}).get("x-permission")
    if raw is None:
        return ()
    return (raw,) if isinstance(raw, str) else tuple(raw)


def api_routes(app: FastAPI) -> list[Any]:
    """Действующие маршруты ``/api/…`` (с учётом префиксов и зависимостей подключения)."""
    return [
        r
        for r in iter_route_contexts(app.routes)
        if isinstance(r.original_route, APIRoute) and str(r.path).startswith(API_PREFIX)
    ]


def problems(app: FastAPI, catalog: Catalog | None = None) -> list[str]:
    catalog = catalog or load_catalog()
    found: list[str] = []
    for route in api_routes(app):
        name = f"{','.join(sorted(route.methods))} {route.path}"
        perms = declared(route)
        if not perms:
            found.append(f"{name}: нет x-permission")
            continue
        unknown = [p for p in perms if p not in catalog.permissions]
        if unknown:
            found.append(f"{name}: права нет в каталоге: {', '.join(unknown)}")
            continue
        calls = set(_calls(route.dependant))
        real = tuple(p for p in perms if p not in PSEUDO)
        gated = {c for call in calls for c in getattr(call, "authz_codes", ())}
        if gated != set(real):
            found.append(f"{name}: x-permission {', '.join(real)} ≠ проверке gate {sorted(gated)}")
        pseudo = [p for p in perms if p in PSEUDO]
        if pseudo and not real and not any(p not in _NEEDS or _NEEDS[p] & calls for p in pseudo):
            found.append(f"{name}: {' или '.join(pseudo)} без зависимости сессии")
    return found


def assert_routes_protected(app: FastAPI) -> None:
    found = problems(app)
    if found:
        raise UnprotectedRouteError("; ".join(found))
