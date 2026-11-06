"""INF-002/INF-008/INF-010: метрики SPEC 18.4 и реестр для треков."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest

from estimator import metrics
from estimator.api.common import ApiRouter, install_error_handlers
from estimator.metrics import QueueLengthCollector


def _scrape(reader) -> str:
    reg = CollectorRegistry()
    reg.register(QueueLengthCollector(reader))
    return generate_latest(reg).decode()


def test_queue_lengths_exported() -> None:
    text = _scrape(lambda: {"default": 3, "exports": 0})
    assert 'estimator_celery_queue_length{queue="default"} 3.0' in text
    assert "estimator_celery_queue_up 1.0" in text


def test_reader_failure_marks_down() -> None:
    def broken() -> dict[str, int]:
        raise ConnectionError

    text = _scrape(broken)
    assert "estimator_celery_queue_up 0.0" in text
    assert "estimator_celery_queue_length{" not in text


# --- INF-010: набор SPEC 18.4 и реестр для треков ---------------------------------------------


def _sample(name: str, **labels: str) -> float:
    value = metrics.REGISTRY.get_sample_value(name, labels)
    return value or 0.0


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    router = ApiRouter()

    @router.get("/things/{thing_id}", permission="public")
    async def get_thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @router.get("/boom", permission="public")
    async def boom() -> None:
        raise RuntimeError("сбой")

    app.include_router(router, prefix="/api/v1")
    app.add_middleware(metrics.RequestMetricsMiddleware)
    return app


@pytest.mark.spec("18.4")
def test_request_metrics_by_route_template() -> None:
    route = "/api/v1/things/{thing_id}"
    before = _sample(
        "estimator_http_responses_total", method="GET", route=route, status_class="2xx"
    )
    count = _sample("estimator_http_request_duration_seconds_count", method="GET", route=route)
    with TestClient(_app(), raise_server_exceptions=False) as client:
        client.get("/api/v1/things/a1")
        client.get("/api/v1/things/b2")
        assert client.get("/api/v1/boom").status_code == 500
        client.get("/api/v1/unknown/xyz")
        client.get("/health/live")
    after = _sample("estimator_http_responses_total", method="GET", route=route, status_class="2xx")
    assert after - before == 2, "идентификаторы не попадают в метки — один ряд на шаблон"
    assert (
        _sample("estimator_http_request_duration_seconds_count", method="GET", route=route) - count
        == 2
    )
    assert (
        _sample(
            "estimator_http_responses_total", method="GET", route="/api/v1/boom", status_class="5xx"
        )
        >= 1
    )
    assert (
        _sample(
            "estimator_http_responses_total", method="GET", route="unmatched", status_class="4xx"
        )
        >= 1
    )
    exported = generate_latest(metrics.REGISTRY).decode()
    assert "/health/live" not in exported, "служебные опросы не считаются"


@pytest.mark.spec("18.4")
def test_login_failures_counter() -> None:
    labels = {"method": "local", "step": "password", "reason": "bad_password"}
    before = _sample("estimator_auth_login_failures_total", **labels)
    metrics.LOGIN_FAILURES.labels(**labels).inc()
    assert _sample("estimator_auth_login_failures_total", **labels) - before == 1


def test_registry_for_tracks_is_idempotent() -> None:
    first = metrics.counter("estimator_test_sync_runs_total", "Тест", ("result",))
    assert metrics.counter("estimator_test_sync_runs_total", "Тест", ("result",)) is first
    with pytest.raises(ValueError, match="другим типом"):
        metrics.gauge("estimator_test_sync_runs_total", "Тест", ("result",))
    with pytest.raises(ValueError, match="начинаться"):
        metrics.counter("sync_runs_total", "Тест")
    gauge = metrics.gauge("estimator_test_ws_connections", "Тест")
    gauge.set(3)
    hist = metrics.histogram("estimator_test_backup_seconds", "Тест", buckets=(1, 10))
    hist.observe(2)
    exported = generate_latest(metrics.REGISTRY).decode()
    assert "estimator_test_ws_connections 3.0" in exported
    assert 'estimator_test_backup_seconds_bucket{le="10.0"} 1.0' in exported


def test_route_label_without_route() -> None:
    assert metrics.route_label({"path": "/x"}) == metrics.UNMATCHED_ROUTE
