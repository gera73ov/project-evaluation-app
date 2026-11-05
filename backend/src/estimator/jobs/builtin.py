"""Служебные задачи каркаса (INF-008)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="estimator.jobs.ping")
def ping() -> str:
    """Проверочная задача: worker жив и читает очередь."""
    return "pong"


@shared_task(name="estimator.jobs.heartbeat")
def heartbeat() -> None:
    """Периодическая проверочная задача: beat ставит её раз в минуту, worker пишет в лог."""
    from estimator.logging import get_logger

    get_logger(__name__).info("beat_heartbeat")
