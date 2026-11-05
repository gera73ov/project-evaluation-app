"""Задачи Celery трека SEC (SEC-004): ежедневная проверка цепочки аудита в 04:00."""

from __future__ import annotations

import asyncio

from celery import shared_task
from celery.schedules import crontab

from estimator.jobs.schedule import PeriodicTask, register_periodic

AUDIT_VERIFY_TASK = "estimator.security.audit_verify"


@shared_task(name=AUDIT_VERIFY_TASK)
def audit_verify() -> bool:
    """Проверить цепочку; сбой — событие с оповещением ИБ (SEC-AUD-03, SEC-AUTH-07)."""
    from estimator.security.audit.runs import verify_and_record

    return asyncio.run(verify_and_record(actor="system")).ok


register_periodic(PeriodicTask("audit_verify", AUDIT_VERIFY_TASK, crontab(hour=4, minute=0)))
