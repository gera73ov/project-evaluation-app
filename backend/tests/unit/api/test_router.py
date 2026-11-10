"""API-003: роутер требует право у каждой операции (SEC-AUTHZ-02), закрыт по умолчанию."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from estimator.api.common import ApiRouter, install_error_handlers
from estimator.api.common import router as router_module

pytestmark = pytest.mark.spec("SEC-AUTHZ-02")


def test_route_without_permission_fails_at_declaration() -> None:
    router = ApiRouter()
    with pytest.raises(TypeError, match="permission"):

        @router.get("/x")
        async def x() -> None: ...


def test_empty_permission_rejected() -> None:
    with pytest.raises(TypeError):
        ApiRouter().post("/x", permission=[])


def _app() -> tuple[FastAPI, TestClient]:
    router = ApiRouter(prefix="/v1")

    @router.get("/open", permission="public")
    async def open_() -> dict:
        return {"ok": True}

    @router.get("/project", permission="project.read")
    async def project() -> dict:
        return {"ok": True}

    @router.post("/totp", permission="token.login_step")
    async def totp() -> dict:
        return {"ok": True}

    @router.get("/any", permission=["money.read", "money.write"])
    async def any_() -> dict:
        return {"ok": True}

    outer = ApiRouter()
    outer.include_router(router)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(outer)
    return app, TestClient(app)


def test_permission_in_openapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_module, "gate", lambda codes, step_up=True: Depends(lambda: None))
    app, _ = _app()
    paths = app.openapi()["paths"]
    assert paths["/v1/open"]["get"]["x-permission"] == "public"
    assert paths["/v1/project"]["get"]["x-permission"] == "project.read"
    assert paths["/v1/any"]["get"]["x-permission"] == ["money.read", "money.write"]
    assert paths["/v1/totp"]["post"]["x-permission"] == "token.login_step"


def test_route_keeps_permission() -> None:
    router = ApiRouter()

    @router.get("/x", permission="project.read")
    async def x() -> None: ...

    assert router.routes[-1].permission == ("project.read",)


def test_gate_of_sec005_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def gate(codes: tuple[str, ...], step_up: bool = True):
        async def check() -> None:
            calls.append(codes)
            if "money.read" in codes:
                raise HTTPException(403, detail={"code": "TOTP_REQUIRED"})

        return Depends(check)

    monkeypatch.setattr(router_module, "gate", gate)
    _, client = _app()
    assert client.get("/v1/open").status_code == 200
    assert client.post("/v1/totp").status_code == 200
    assert client.get("/v1/project").status_code == 200
    r = client.get("/v1/any")
    assert (r.status_code, r.json()["code"]) == (403, "TOTP_REQUIRED")
    assert calls == [("project.read",), ("money.read", "money.write")]


@pytest.mark.spec("SEC-AUTH-05")
def test_step_up_is_per_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, bool] = {}

    def gate(codes: tuple[str, ...], step_up: bool = True):
        seen[codes[0]] = step_up
        return Depends(lambda: None)

    monkeypatch.setattr(router_module, "gate", gate)
    router = ApiRouter()

    @router.post("/write", permission="system.settings.write")
    async def write() -> None: ...

    @router.get("/list", permission="system.users.anonymize", step_up=False)
    async def list_() -> None: ...

    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]
    assert paths["/write"]["post"]["x-step-up"] is True
    assert "x-step-up" not in paths["/list"]["get"]
    assert seen == {"system.settings.write": True, "system.users.anonymize": False}
    with pytest.raises(TypeError, match="step-up"):

        @router.get("/read", permission="project.read", step_up=True)
        async def read() -> None: ...
