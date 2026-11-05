"""INF-002/INF-008: сборщик длины очередей Celery (SPEC 18.4)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, generate_latest

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
