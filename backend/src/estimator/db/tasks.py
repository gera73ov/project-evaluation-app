"""Периодические задачи трека DB (DB-009).

``estimator.db.ensure_audit_partitions`` — раз в сутки создаёт партиции ``audit.audit_log`` на
текущий месяц и 3 месяца вперёд (функция ``audit.ensure_partitions``, миграция ``0003_audit``).
Пропуск запусков не теряет записи: они попадают в партицию по умолчанию.
"""

from __future__ import annotations

import asyncio

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from estimator.config import get_settings
from estimator.db.session import create_engine
from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger

log = get_logger(__name__)

#: Сколько месяцев вперёд держать готовые партиции журнала аудита (DB-009).
AUDIT_MONTHS_AHEAD = 3


async def ensure_audit_partitions_async(months_ahead: int = AUDIT_MONTHS_AHEAD) -> int:
    engine = create_engine(get_settings(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            created = await conn.scalar(
                text("SELECT audit.ensure_partitions(:n)"), {"n": months_ahead}
            )
    finally:
        await engine.dispose()
    log.info("audit_partitions_ensured", created=created, months_ahead=months_ahead)
    return int(created or 0)


@shared_task(name="estimator.db.ensure_audit_partitions")
def ensure_audit_partitions() -> int:
    return asyncio.run(ensure_audit_partitions_async())


register_periodic(
    PeriodicTask(
        "db.ensure_audit_partitions",
        "estimator.db.ensure_audit_partitions",
        crontab(hour=2, minute=30),
    )
)
