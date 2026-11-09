"""Периодические задачи трека RT: ночная очистка ``change_log`` (RT-007, NFR-REL-06)."""

from __future__ import annotations

import asyncio

from celery import shared_task
from celery.schedules import crontab

from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger

log = get_logger(__name__)

PURGE_TASK = "estimator.realtime.purge_change_log"


async def purge_change_log_async() -> int:
    from estimator.db.session import dispose_engine, transaction
    from estimator.realtime.changes import purge

    try:
        async with transaction() as db:
            deleted = await purge(db)
    finally:
        await dispose_engine()
    log.info("change_log_purged", deleted=deleted)
    return deleted


@shared_task(name=PURGE_TASK)
def purge_change_log() -> int:
    return asyncio.run(purge_change_log_async())


register_periodic(PeriodicTask("realtime.purge_change_log", PURGE_TASK, crontab(hour=3, minute=15)))
