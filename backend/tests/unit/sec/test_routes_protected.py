"""TC-SEC-01: каждый маршрут API объявляет право из каталога и проверяет его (SEC-AUTHZ-02)."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI

from estimator import health
from estimator.auth.mfa_policy import ActivePrincipal, PreMfaPrincipal
from estimator.config import Settings
from estimator.main import create_app
from estimator.security.authz import Access, gate, require
from estimator.security.authz.routes import (
    UnprotectedRouteError,
    api_routes,
    assert_routes_protected,
    problems,
)

pytestmark = [pytest.mark.spec("SEC-AUTHZ-02"), pytest.mark.spec("TC-SEC-01")]


def _perm(code: str | list[str]) -> dict[str, object]:
    return {"x-permission": code}


def test_application_routes_are_protected() -> None:
    app = create_app(Settings(), probes=health.Probes())
    assert problems(app) == []
    paths = {r.path for r in api_routes(app)}
    assert {"/api/v1/auth/login", "/api/v1/me/password"} <= paths


def _app(router: APIRouter) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def test_route_without_permission_fails() -> None:
    router = APIRouter()

    @router.get("/open")
    async def open_route() -> None: ...

    with pytest.raises(UnprotectedRouteError, match="нет x-permission"):
        assert_routes_protected(_app(router))


def test_unknown_permission_fails() -> None:
    router = APIRouter()

    @router.get("/x", openapi_extra=_perm("tree.write.any"))
    async def x() -> None: ...

    assert "нет в каталоге" in problems(_app(router))[0]


def test_declared_but_not_checked_fails() -> None:
    router = APIRouter()

    @router.get("/projects/{id}/tree", openapi_extra=_perm("tree.read"))
    async def tree(principal: ActivePrincipal) -> None: ...

    @router.get("/projects/{id}/other", openapi_extra=_perm("tree.read"),
                dependencies=[gate("project.read")])  # fmt: skip
    async def other() -> None: ...

    found = problems(_app(router))
    assert len(found) == 2
    assert all("gate" in f for f in found)


def test_pseudo_permissions_need_session_dependency() -> None:
    router = APIRouter()

    @router.get("/me-ok", openapi_extra=_perm("authenticated"))
    async def me_ok(principal: ActivePrincipal) -> None: ...

    @router.get("/me-bad", openapi_extra=_perm("authenticated"))
    async def me_bad(principal: PreMfaPrincipal) -> None: ...

    @router.post("/logout", openapi_extra=_perm(["authenticated", "session.pre_mfa"]))
    async def logout(principal: PreMfaPrincipal) -> None: ...

    @router.post("/login", openapi_extra=_perm("public"))
    async def login() -> None: ...

    @router.post("/activate", openapi_extra=_perm("token.activation"))
    async def activate() -> None: ...

    found = problems(_app(router))
    assert found == ["GET /api/v1/me-bad: authenticated без зависимости сессии"]


def test_gate_and_require_in_handler_signature() -> None:
    router = APIRouter()

    @router.get("/projects/{id}/tree", openapi_extra=_perm("tree.read"))
    async def tree(access: Annotated[Access, require("tree.read")]) -> None: ...

    @router.get(
        "/system/audit",
        openapi_extra=_perm(["audit.read.all", "audit.read.admin_categories"]),
        dependencies=[gate(("audit.read.all", "audit.read.admin_categories"))],
    )
    async def audit_log() -> None: ...  # fmt: skip

    assert problems(_app(router)) == []


def test_non_api_routes_are_ignored() -> None:
    app = FastAPI()

    @app.get("/health/live")
    async def live() -> None: ...

    assert problems(app) == []


@pytest.mark.parametrize("codes", [(), "public", ("tree.read", "authenticated"), "nope"])
def test_gate_rejects_bad_codes(codes: object) -> None:
    with pytest.raises((ValueError, KeyError)):
        gate(codes)  # type: ignore[arg-type]


def test_gate_is_a_dependency() -> None:
    dep = gate("tree.read")
    assert isinstance(dep, type(Depends(lambda: None)))
    assert dep.dependency.authz_codes == ("tree.read",)


def test_resolver_prefix_must_end_with_id() -> None:
    from estimator.security.authz import register_resolver

    async def resolver(_db: object, _id: object) -> None: ...

    with pytest.raises(ValueError, match=r"/\{id\}"):
        register_resolver("/nodes", resolver)  # type: ignore[arg-type]
