"""Метрики Prometheus (INF-002, INF-008, INF-010; SPEC 13.1, 18.4, NFR-MNT-05).

``/metrics`` доступен только из внутренней сети: публичный Nginx его не проксирует (INF-009),
Prometheus стенда ходит к API напрямую (deploy/monitoring/prometheus.yml).

Набор SPEC 18.4:

* ``estimator_http_request_duration_seconds`` — гистограмма времени ответа по эндпоинтам
  (шаблон пути, не сам путь: без идентификаторов в метках); p95 —
  ``histogram_quantile(0.95, sum by (le, route) (rate(..._bucket[5m])))``;
* ``estimator_http_responses_total`` — ответы по классу кода, 5xx — ``status_class="5xx"``;
* ``estimator_auth_login_failures_total`` — неуспешные входы; в минуту —
  ``sum(rate(...[1m])) * 60``;
* ``estimator_celery_queue_length`` — длина очередей Celery (:class:`QueueLengthCollector`).

Метрики других треков (WS, синхронизация AD, бэкап, SIEM) объявляются через :func:`counter`,
:func:`gauge`, :func:`histogram` в этом же реестре: повторное объявление с теми же параметрами
возвращает уже созданную метрику, с другими — ошибка.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, make_asgi_app
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.metrics import MetricWrapperBase
from prometheus_client.registry import Collector

from estimator.logging import get_logger

log = get_logger(__name__)

#: Отдельный реестр приложения: в тестах не пересекается с глобальным.
REGISTRY = CollectorRegistry(auto_describe=True)
PREFIX = "estimator_"
#: Пути, которые не считаются запросами API (служебные опросы)
UNTRACKED_PREFIXES = ("/metrics", "/health")
UNMATCHED_ROUTE = "unmatched"
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

_declared: dict[str, tuple[type[MetricWrapperBase], tuple[str, ...], MetricWrapperBase]] = {}


def _declare[M: MetricWrapperBase](
    kind: type[M], name: str, doc: str, labels: Sequence[str], **kwargs: Any
) -> M:
    if not name.startswith(PREFIX):
        raise ValueError(f"метрика {name!r} должна начинаться с {PREFIX!r}")
    labels = tuple(labels)
    if name in _declared:
        known_kind, known_labels, metric = _declared[name]
        if known_kind is not kind or known_labels != labels:
            raise ValueError(f"метрика {name!r} уже объявлена с другим типом или метками")
        return metric  # type: ignore[return-value]
    metric = kind(name, doc, labels, registry=REGISTRY, **kwargs)
    _declared[name] = (kind, labels, metric)
    return metric


def counter(name: str, doc: str, labels: Sequence[str] = ()) -> Counter:
    """Счётчик в реестре приложения (для метрик треков)."""
    return _declare(Counter, name, doc, labels)


def gauge(name: str, doc: str, labels: Sequence[str] = ()) -> Gauge:
    return _declare(Gauge, name, doc, labels)


def histogram(
    name: str, doc: str, labels: Sequence[str] = (), buckets: Sequence[float] = LATENCY_BUCKETS
) -> Histogram:
    return _declare(Histogram, name, doc, labels, buckets=tuple(buckets))


REQUEST_DURATION = histogram(
    "estimator_http_request_duration_seconds",
    "Время ответа API по эндпоинтам, секунды (SPEC 18.4)",
    ("method", "route"),
)
RESPONSES = counter(
    "estimator_http_responses_total",
    "Ответы API по классу кода (SPEC 18.4: 5xx)",
    ("method", "route", "status_class"),
)
LOGIN_FAILURES = counter(
    "estimator_auth_login_failures_total",
    "Неуспешные входы (SPEC 18.4); в минуту — rate(...[1m]) * 60",
    ("method", "step", "reason"),
)


def route_label(scope: dict[str, Any]) -> str:
    """Шаблон пути маршрута (``/api/v1/projects/{project_id}``) или ``unmatched``.

    У маршрутов вложенных роутеров FastAPI шаблон хранится без префикса (``/projects/{id}``):
    префикс восстанавливается из начальных сегментов фактического пути.
    """
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not template:
        return UNMATCHED_ROUTE
    template = str(template)
    actual = [p for p in str(scope.get("path", "")).split("/") if p]
    tail = [p for p in template.split("/") if p]
    extra = len(actual) - len(tail)
    if extra > 0:
        return "/" + "/".join(actual[:extra] + tail)
    return template


class RequestMetricsMiddleware:
    """Время ответа и класс кода по эндпоинтам; служебные пути не считаются.

    Чистый ASGI-слой. Маршрут берётся из ``scope["route"]``, который маршрутизатор Starlette
    дописывает в тот же ``scope`` при сопоставлении; несопоставленные пути (404 сканеров)
    сводятся в одну метку, чтобы число рядов не росло.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(UNTRACKED_PREFIXES):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def tracked(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        finally:
            method = scope.get("method", "")
            route = route_label(scope)
            REQUEST_DURATION.labels(method, route).observe(time.perf_counter() - started)
            RESPONSES.labels(method, route, f"{status // 100}xx").inc()


class QueueLengthCollector(Collector):
    """Длина очередей Celery в Redis (SPEC 18.4 «длина очереди Celery»).

    Читает длину при каждом опросе. ``reader`` возвращает ``{очередь: длина}``; если Redis
    недоступен, метрика длины не отдаётся, а ``estimator_celery_queue_up`` = 0.
    """

    def __init__(self, reader: Callable[[], dict[str, int]]) -> None:
        self._reader = reader

    def collect(self) -> Iterator[GaugeMetricFamily]:
        up = GaugeMetricFamily(
            "estimator_celery_queue_up", "Удалось ли прочитать длину очередей Celery (1/0)"
        )
        try:
            lengths = self._reader()
        except Exception as exc:  # noqa: BLE001 — сбой опроса не должен ронять /metrics
            log.warning("queue_length_read_failed", error_type=type(exc).__name__)
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up
        gauge = GaugeMetricFamily(
            "estimator_celery_queue_length", "Число задач в очереди Celery", labels=["queue"]
        )
        for queue, length in sorted(lengths.items()):
            gauge.add_metric([queue], length)
        yield gauge


def metrics_app(registry: CollectorRegistry = REGISTRY):
    """ASGI-приложение, отдающее метрики реестра."""
    return make_asgi_app(registry=registry)
