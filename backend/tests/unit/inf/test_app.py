"""INF-002: фабрика приложения, /health/*, /metrics (NFR-MNT-05)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from estimator.config import Settings
from estimator.health import Probes, default_probes
from estimator.main import create_app

pytestmark = pytest.mark.spec("NFR-MNT-05")


def _probes(**results: bool) -> Probes:
    probes = Probes()
    for name, ok in results.items():

        async def check(ok: bool = ok) -> None:
            if not ok:
                raise ConnectionError("down")

        probes.add(name, check)
    return probes


def _client(probes: Probes, **settings: object) -> TestClient:
    return TestClient(create_app(Settings(**settings), probes=probes))


def test_live_is_200_without_dependencies() -> None:
    with _client(_probes(database=False, redis=False)) as c:
        r = c.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_ok() -> None:
    with _client(_probes(database=True, redis=True)) as c:
        r = c.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.parametrize("down", ["database", "redis"])
def test_ready_reflects_failure(down: str) -> None:
    results = {"database": True, "redis": True, down: False}
    with _client(_probes(**results)) as c:
        r = c.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"
    assert body["checks"][down] == "fail"
    assert "down" not in r.text  # текст ошибки наружу не отдаётся


def test_ready_times_out() -> None:
    probes = Probes()

    async def slow() -> None:
        await asyncio.sleep(1)

    probes.add("database", slow)
    with _client(probes, health_timeout_seconds=0.01) as c:
        r = c.get("/health/ready")
    assert r.status_code == 503


def test_request_id_header() -> None:
    with _client(_probes()) as c:
        generated = c.get("/health/live").headers["x-request-id"]
        echoed = c.get("/health/live", headers={"X-Request-ID": "req-12345678"})
    assert len(generated) == 36
    assert echoed.headers["x-request-id"] == "req-12345678"


def test_docs_disabled_in_prod() -> None:
    with _client(_probes(), app_env="prod") as c:
        assert c.get("/api/openapi.json").status_code == 404
    with _client(_probes(), app_env="dev") as c:
        assert c.get("/api/openapi.json").status_code == 200


def test_trusted_hosts() -> None:
    with _client(_probes(), trusted_hosts=["est.local"]) as c:
        assert c.get("/health/live").status_code == 400
        assert c.get("/health/live", headers={"Host": "est.local"}).status_code == 200


def test_metrics_endpoint() -> None:
    with _client(_probes()) as c:
        r = c.get("/metrics/")
    assert r.status_code == 200


async def test_default_probes_fail_without_services() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://u@127.0.0.1:1/x",
        redis_url="redis://127.0.0.1:1/0",
        health_timeout_seconds=0.5,
    )
    probes = default_probes(s)
    assert probes.names == ["database", "redis"]
    result = await probes.run(0.5)
    await probes.close()
    assert result == {"database": "fail", "redis": "fail"}


@pytest.mark.spec("NFR-PERF-02")
def test_tune_gc_freezes_startup_objects() -> None:
    import gc

    from estimator.main import GC_THRESHOLDS, tune_gc

    before = gc.get_threshold()
    try:
        tune_gc()
        assert gc.get_threshold() == GC_THRESHOLDS
        assert gc.get_freeze_count() > 0
    finally:
        gc.unfreeze()
        gc.set_threshold(*before)
