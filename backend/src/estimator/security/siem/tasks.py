"""Задача Celery отправки аудита в SIEM (SEC-012): каждые 10 секунд, один проход за раз."""

from __future__ import annotations

import asyncio

from celery import shared_task
from celery.schedules import schedule

from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger

log = get_logger(__name__)

SHIP_TASK = "estimator.security.siem_ship"
LOCK_KEY = "siem:ship:lock"
LOCK_TTL = 300
INTERVAL_SECONDS = 10


async def _run() -> int:
    from redis.asyncio import Redis

    from estimator.config import get_settings
    from estimator.db.session import create_engine
    from estimator.security.siem import shipper

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    engine = create_engine(settings)
    lock = redis.lock(LOCK_KEY, timeout=LOCK_TTL, blocking=False)
    try:
        if not await lock.acquire():
            return 0  # предыдущий проход ещё идёт
        try:
            async with engine.connect() as conn:
                result = await shipper.ship(conn, redis)
        finally:
            await lock.release()
        return result.sent
    finally:
        await engine.dispose()
        await redis.aclose()


@shared_task(name=SHIP_TASK, ignore_result=True)
def ship() -> int:
    """Досылка очереди в SIEM и копия в stdout (SEC-AUD-05)."""
    return asyncio.run(_run())


register_periodic(PeriodicTask("siem_ship", SHIP_TASK, schedule(INTERVAL_SECONDS)))
