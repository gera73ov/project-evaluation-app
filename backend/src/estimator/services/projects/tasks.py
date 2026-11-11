"""CORE-028 · ночная автоархивация (SPEC BR-PRJ-03, Q-13, 7.5, G-25).

Проекты в «Завершена» дольше ``method.autoarchive_days`` дней от ``completed_at`` переводятся в
«Архив». Срок один на все проекты; 0 — автоархивация выключена. Граница считается по датам в
часовом поясе приложения: проект, завершённый в день D, архивируется в ночь после дня
D + срок. Каждый переход — запись журнала от имени «Система» (``user_id`` пуст), аудит
``project.status.changed`` с ``automatic: true`` и событие ``project.updated``. Задача — в 01:30.
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
from estimator.security import audit
from estimator.services.common import app_timezone, emit
from estimator.services.projects import journal

AUTOARCHIVE_TASK = "estimator.projects.autoarchive"


async def autoarchive(db: AsyncSession, now: dt.datetime | None = None) -> list[uuid.UUID]:
    """Перевести в «Архив» завершённые проекты старше срока; ID переведённых."""
    days = int((await method.current(db))["autoarchive_days"])
    if days <= 0:
        return []
    now = now or dt.datetime.now(dt.UTC)
    zone = await app_timezone(db)
    # Начало дня (today − срок) в поясе приложения: всё, что завершено раньше, — в архив.
    cutoff_day = now.astimezone(zone).date() - dt.timedelta(days=days)
    cutoff = dt.datetime.combine(cutoff_day, dt.time(), tzinfo=zone)
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
    moved: list[uuid.UUID] = []
    for project in projects:
        project.status = ProjectStatus.ARCHIVED
        project.archived_at = now
        project.cancel_reason = None
        await db.flush()
        changes = {"status": (ProjectStatus.COMPLETED.value, ProjectStatus.ARCHIVED.value)}
        journal.record(db, project.id, None, "project.status", changes)
        await audit.write(
            db,
            "project.status.changed",
            actor="system",
            object_type="project",
            object_id=project.id,
            project_id=project.id,
            details={
                "from": ProjectStatus.COMPLETED.value,
                "to": ProjectStatus.ARCHIVED.value,
                "automatic": True,
                "cancel_reason": None,
            },
        )
        project.version = await emit(
            db, project.id, "project.updated", {"changes": {"status": "archived"}, "author": None}
        )
        moved.append(project.id)
    return moved


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
