"""CORE-028: ночная автоархивация — «Завершена» дольше срока → «Архив», запись журнала от имени
«Система», аудит с ``automatic: true``; срок 0 выключает (BR-PRJ-03, Q-13, G-25)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project
from estimator.db.models.settings import SystemSetting
from estimator.db.models.tree import ProjectJournal
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.projects.tasks import autoarchive
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.helpers import audit_details, create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("BR-PRJ-03")]

NOW = dt.datetime(2026, 11, 11, 22, 30, tzinfo=dt.UTC)


async def _completed(db: AsyncSession, pid: uuid.UUID, days_ago: int) -> None:
    await db.execute(
        update(Project)
        .where(Project.id == pid)
        .values(status=ProjectStatus.COMPLETED, completed_at=NOW - dt.timedelta(days=days_ago))
    )
    await db.flush()


async def test_autoarchive(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    old = await create_project(world, moderator)
    fresh = await create_project(world, moderator)
    estimating = await create_project(world, moderator)
    await _completed(db_session, old, 182)
    await _completed(db_session, fresh, 100)
    await db_session.execute(
        update(Project)
        .where(Project.id == estimating)
        .values(status=ProjectStatus.ESTIMATION, completed_at=NOW - dt.timedelta(days=400))
    )

    assert await autoarchive(db_session, now=NOW) == [old]
    await deliver_events(db_session)
    project = await db_session.get(Project, old, populate_existing=True)
    assert project is not None
    assert (project.status, project.archived_at) == (ProjectStatus.ARCHIVED, NOW)
    statuses = {
        p.id: p.status
        for p in await db_session.scalars(
            select(Project)
            .where(Project.id.in_([fresh, estimating]))
            .execution_options(populate_existing=True)
        )
    }
    assert statuses == {fresh: ProjectStatus.COMPLETED, estimating: ProjectStatus.ESTIMATION}

    [entry] = await db_session.scalars(
        select(ProjectJournal).where(
            ProjectJournal.project_id == old, ProjectJournal.action == "project.status"
        )
    )
    assert entry.user_id is None  # «Система»
    assert entry.changes == {"status": ["completed", "archived"]}
    [details] = await audit_details(db_session, "project.status.changed", old)
    assert details["automatic"] is True
    assert details["actor"] == "system"
    [event] = [e for e in events.on(f"project:{old}") if e["event"] == "project.updated"]
    assert event["data"] == {"changes": {"status": "archived"}, "author": None}
    journal = (await moderator.get(f"/projects/{old}/journal")).json()["items"]
    assert journal[0]["user"] is None

    assert await autoarchive(db_session, now=NOW) == []  # повтор ничего не делает


async def test_autoarchive_disabled(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await _completed(db_session, pid, 1000)
    await db_session.merge(SystemSetting(key="method.autoarchive_days", value=0))
    await db_session.flush()
    assert await autoarchive(db_session, now=NOW) == []
    await db_session.merge(SystemSetting(key="method.autoarchive_days", value=30))
    await db_session.flush()
    assert await autoarchive(db_session, now=NOW) == [pid]
