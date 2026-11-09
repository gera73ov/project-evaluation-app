"""Ночная очистка корзины (SPEC FR-TREE-24, Q-04): узлы, удалённые больше 30 дней назад,
удаляются окончательно вместе с историей и обсуждениями (каскад FK). Задача — в 02:30."""

from __future__ import annotations

import asyncio
import datetime as dt

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.tree import Node
from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.services.trash.listing import RETENTION

PURGE_TASK = "estimator.trash.purge"


async def purge(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Окончательно удалить узлы корзины старше 30 дней; число удалённых строк."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - RETENTION
    result = await db.execute(
        delete(Node)
        .where(Node.deleted_at.is_not(None), Node.deleted_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _run() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.config import get_settings
    from estimator.db.session import create_engine

    engine = create_engine(get_settings())  # свой движок: у asyncio.run свой цикл событий
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return await purge(db)
    finally:
        await engine.dispose()


@shared_task(name=PURGE_TASK)
def purge_trash() -> int:
    return asyncio.run(_run())


register_periodic(PeriodicTask("trash_purge", PURGE_TASK, crontab(hour=2, minute=30)))
