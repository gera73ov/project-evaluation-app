"""CORE-028 · ночная автоархивация (SPEC BR-PRJ-03, Q-13, 7.5, G-25).

Проекты в «Завершена» дольше ``method.autoarchive_days`` от ``completed_at`` переходят в «Архив».
Срок 0 выключает автоархивацию. Переход пишется в журнал проекта без пользователя (в ленте —
«Система»), в аудит ``project.status.changed`` с ``automatic: true`` (``actor: system``) и
событием ``project.updated`` с ``author: null``. Срок меняется в справочнике «Методика» и сразу
действует на все проекты (7.5). Задача идёт в 01:30 по часовому поясу приложения (Celery
``timezone = APP_TIMEZONE``).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.dictionaries import method
from estimator.db.enums import ProjectStatus
from estimator.db.models.projects import Project
from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger
from estimator.security import audit
from estimator.services.common import emit
from estimator.services.projects import journal

AUTOARCHIVE_TASK = "estimator.projects.autoarchive"

log = get_logger(__name__)


async def autoarchive(db: AsyncSession, now: dt.datetime | None = None) -> list[uuid.UUID]:
    """Перевести в «Архив» завершённые проекты старше срока; id переведённых."""
    days = int((await method.current(db))["autoarchive_days"])
    if days <= 0:
        return []
    moment = now or dt.datetime.now(dt.UTC)
    cutoff = moment - dt.timedelta(days=days)
    projects = (
        await db.scalars(
            select(Project)
            .where(
                Project.status == ProjectStatus.COMPLETED,
                Project.completed_at.is_not(None),
                Project.completed_at < cutoff,
            )
            .order_by(Project.completed_at)
            .with_for_update(skip_locked=True)
        )
    ).all()
    done: list[uuid.UUID] = []
    for project in projects:
        frm = ProjectStatus(project.status)
        project.status = ProjectStatus.ARCHIVED
        project.archived_at = moment
        project.cancel_reason = None
        await db.flush()
        journal.record(
            db,
            project.id,
            None,
            "project.status",
            {"status": (frm.value, ProjectStatus.ARCHIVED.value)},
        )
        await audit.write(
            db,
            "project.status.changed",
            actor="system",
            object_type="project",
            object_id=project.id,
            project_id=project.id,
            details={
                "from": frm.value,
                "to": ProjectStatus.ARCHIVED.value,
                "automatic": True,
                "cancel_reason": None,
            },
        )
        project.version = await emit(
            db,
            project.id,
            "project.updated",
            {"changes": {"status": ProjectStatus.ARCHIVED.value}, "author": None},
        )
        done.append(project.id)
    if done:
        log.info("projects_autoarchived", count=len(done), days=days)
    return done


async def _run() -> int:  # pragma: no cover — запуск в worker
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.config import get_settings
    from estimator.db.session import create_engine

    engine = create_engine(get_settings())  # свой движок: у asyncio.run свой цикл событий
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return len(await autoarchive(db))
    finally:
        await engine.dispose()


@shared_task(name=AUTOARCHIVE_TASK)
def autoarchive_projects() -> int:  # pragma: no cover — запуск в worker
    return asyncio.run(_run())


register_periodic(
    PeriodicTask("projects_autoarchive", AUTOARCHIVE_TASK, crontab(hour=1, minute=30))
)
