"""API-003: ответы RFC 9457 с code и error_id; 500 без трассировки (SEC-WEB-09)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from estimator.api.common import ApiError, install_error_handlers, new_error_id

pytestmark = pytest.mark.spec("15.1")

ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=5)


def _app() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/conflict")
    async def conflict() -> None:
        raise ApiError(
            "FIELD_CONFLICT",
            detail="Поле r изменено",
            conflicts=[{"field": "r"}],
            current_version=9,
            secret="не попадёт в ответ",
        )

    @app.get("/limited")
    async def limited() -> None:
        raise HTTPException(
            429, detail={"code": "RATE_LIMITED", "retry_after": 30}, headers={"Retry-After": "30"}
        )

    @app.get("/plain")
    async def plain() -> None:
        raise HTTPException(403)

    @app.post("/body")
    async def body(data: Body) -> Body:
        return data

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("password=hunter2 в трассировке")

    return TestClient(app, raise_server_exceptions=False)


def test_api_error_is_problem_json() -> None:
    r = _app().get("/conflict")
    assert r.status_code == 409
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert ULID.match(body.pop("error_id"))
    assert body == {
        "type": "https://estimator.local/problems/field-conflict",
        "title": "Значение уже изменено",
        "status": 409,
        "code": "FIELD_CONFLICT",
        "detail": "Поле r изменено",
        "instance": "/conflict",
        "conflicts": [{"field": "r"}],
        "current_version": 9,
    }


def test_http_exception_with_code_keeps_extensions_and_headers() -> None:
    """Совместимость с HTTPException(detail={"code": ...}) модулей auth/security."""
    r = _app().get("/limited")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert r.json()["code"] == "RATE_LIMITED"
    assert r.json()["retry_after"] == 30


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [("/plain", 403, "FORBIDDEN"), ("/nope", 404, "NOT_FOUND"), ("/body", 404, "NOT_FOUND")],
    ids=["403", "404", "405"],
)
def test_plain_statuses_map_to_codes(path: str, status: int, code: str) -> None:
    r = _app().get(path)
    assert (r.status_code, r.json()["code"]) == (status, code)


def test_validation_failed_lists_fields() -> None:
    r = _app().post("/body", json={"title": "слишком длинно", "extra": 1})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert {(e["field"], e["code"]) for e in body["errors"]} == {
        ("/title", "too_long"),
        ("/extra", "unknown_field"),
    }


def test_invalid_json_is_malformed_request() -> None:
    r = _app().post("/body", content=b"{", headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()["code"]) == (400, "MALFORMED_REQUEST")


@pytest.mark.spec("SEC-WEB-09")
def test_500_has_only_error_id(caplog: pytest.LogCaptureFixture) -> None:
    r = _app().get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert set(body) == {"type", "title", "status", "code", "error_id", "instance"}
    assert body["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text
    assert "Traceback" not in r.text


@pytest.mark.spec("SEC-WEB-09")
def test_500_in_real_app_has_security_headers() -> None:
    """TC-SEC-08: ответ 500 проходит через SecurityHeadersMiddleware (заголовки и на ошибках)."""
    from estimator.config import Settings
    from estimator.health import Probes
    from estimator.main import create_app

    app = create_app(Settings(), probes=Probes())

    @app.get("/api/v1/boom-in-app")
    async def boom_in_app() -> None:
        raise RuntimeError("секрет в трассировке")

    with TestClient(app, raise_server_exceptions=False, base_url="https://localhost") as client:
        r = client.get("/api/v1/boom-in-app")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "detail" not in r.json()
    assert "секрет" not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in r.headers
    assert "x-request-id" in r.headers


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValueError, match=r"errors\.yaml"):
        ApiError("NO_SUCH_CODE")


def test_error_ids_are_unique_ulids() -> None:
    ids = {new_error_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(ULID.match(i) for i in ids)
