"""Задачи Celery синхронизации с AD (AUTH-016): каждые 15 минут и ежедневно в 03:00."""

from __future__ import annotations

import asyncio

from celery import shared_task

SESSIONS_TASK = "estimator.auth.ad_sync.sessions"
DAILY_TASK = "estimator.auth.ad_sync.daily"


async def _run(kind: str) -> int:  # pragma: no cover — запуск в worker
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.auth import ad_sync
    from estimator.config import get_settings
    from estimator.db.session import create_engine, transaction

    settings = get_settings()
    engine = create_engine(settings)
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        async with transaction(async_sessionmaker(engine)) as db:
            return (await ad_sync.run(db, redis, kind)).checked
    finally:
        await redis.aclose()
        await engine.dispose()


@shared_task(name=SESSIONS_TASK)
def check_active_sessions() -> int:  # pragma: no cover — запуск в worker
    from estimator.auth.ad_sync import SESSIONS

    return asyncio.run(_run(SESSIONS))


@shared_task(name=DAILY_TASK)
def daily_sync() -> int:  # pragma: no cover — запуск в worker
    from estimator.auth.ad_sync import DAILY

    return asyncio.run(_run(DAILY))


def _register() -> None:
    from celery.schedules import crontab

    from estimator.jobs.schedule import PeriodicTask, register_periodic

    register_periodic(PeriodicTask("ad_sync_sessions", SESSIONS_TASK, crontab(minute="*/15")))
    register_periodic(PeriodicTask("ad_sync_daily", DAILY_TASK, crontab(hour=3, minute=0)))


_register()
