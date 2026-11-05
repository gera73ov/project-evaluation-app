"""Метрики Prometheus (каркас INF-002, INF-008; полный набор SPEC 18.4 — INF-010).

NFR-MNT-05: ``/metrics`` доступен только из внутренней сети, публичный Nginx его не проксирует.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from prometheus_client import CollectorRegistry, make_asgi_app
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from estimator.logging import get_logger

log = get_logger(__name__)

#: Отдельный реестр приложения: в тестах не пересекается с глобальным.
REGISTRY = CollectorRegistry(auto_describe=True)


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
