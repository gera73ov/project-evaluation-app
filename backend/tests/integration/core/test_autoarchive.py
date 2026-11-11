"""CORE-028: ночная автоархивация завершённых проектов (BR-PRJ-03, Q-13, 7.5, G-25)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project
from estimator.db.models.settings import SystemSetting
from estimator.db.models.tree import ProjectJournal
from estimator.jobs.schedule import build_beat_schedule
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.projects.tasks import AUTOARCHIVE_TASK, autoarchive
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.helpers import audit_details, create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("BR-PRJ-03"), pytest.mark.spec("Q-13")]

NOW = dt.datetime(2026, 11, 11, 22, 30, tzinfo=dt.UTC)


async def _completed(world: World, db: AsyncSession, days_ago: float) -> uuid.UUID:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await db.execute(
        update(Project)
        .where(Project.id == pid)
        .values(status=ProjectStatus.COMPLETED, completed_at=NOW - dt.timedelta(days=days_ago))
    )
    await db.flush()
    return pid


async def _set_days(db: AsyncSession, days: int) -> None:
    stmt = insert(SystemSetting).values(key="method.autoarchive_days", value=days)
    await db.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": days}))
    await db.flush()


async def _status(db: AsyncSession, pid: uuid.UUID) -> ProjectStatus:
    return (await db.get(Project, pid, populate_existing=True)).status


async def test_archives_after_term_from_system(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    old = await _completed(world, db_session, 181)
    fresh = await _completed(world, db_session, 179)

    assert await autoarchive(db_session, NOW) == [old]
    assert await _status(db_session, old) is ProjectStatus.ARCHIVED
    assert await _status(db_session, fresh) is ProjectStatus.COMPLETED
    project = await db_session.get(Project, old)
    assert project.archived_at == NOW

    [entry] = (
        await db_session.scalars(
            select(ProjectJournal).where(
                ProjectJournal.project_id == old, ProjectJournal.action == "project.status"
            )
        )
    ).all()
    assert entry.user_id is None  # в ленте — «Система»
    assert entry.changes == {"status": ["completed", "archived"]}
    [details] = await audit_details(db_session, "project.status.changed", old)
    assert details["automatic"] is True
    assert details["to"] == "archived"

    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{old}") if e["event"] == "project.updated"]
    assert event["data"] == {"changes": {"status": "archived"}, "author": None}

    # повторный запуск ничего не трогает
    assert await autoarchive(db_session, NOW) == []


async def test_term_is_configurable_and_zero_disables(
    world: World, db_session: AsyncSession
) -> None:
    pid = await _completed(world, db_session, 40)
    await _set_days(db_session, 0)
    assert await autoarchive(db_session, NOW) == []
    await _set_days(db_session, 30)  # новый срок сразу действует на все проекты (7.5)
    assert await autoarchive(db_session, NOW) == [pid]


def test_nightly_task_registered() -> None:
    assert build_beat_schedule()["projects_autoarchive"]["task"] == AUTOARCHIVE_TASK
