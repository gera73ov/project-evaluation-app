"""API-005: документация OpenAPI только на стендах (SPEC 15.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from estimator import health
from estimator.config import Settings
from estimator.main import create_app

DOC_PATHS = ("/api/docs", "/api/openapi.json", "/api/docs/oauth2-redirect", "/redoc")


def _client(app_env: str) -> TestClient:
    return TestClient(create_app(Settings(app_env=app_env), probes=health.Probes()))


def test_prod_has_no_docs() -> None:
    with _client("prod") as client:
        for path in DOC_PATHS:
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("app_env", ["dev", "test", "stage"])
def test_stands_have_docs(app_env: str) -> None:
    with _client(app_env) as client:
        assert client.get("/api/openapi.json").status_code == 200
        page = client.get("/api/docs")
        assert page.status_code == 200
        assert "swagger" in page.text.lower()
        assert client.get("/redoc").status_code == 404
