"""QA-017 · шаги сценариев портфеля и жизненного цикла (SPEC 17.2): G-21 «Руководитель пресейла и
архив», G-25 «Автоархивация» (шаг «отработала ночная задача» — в tree_steps)."""

from __future__ import annotations

import datetime as dt

from pytest_bdd import given, parsers, then, when
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project
from estimator.db.models.settings import SystemSetting
from tests.acceptance.steps.common import Scene, aio
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project

STATUS = {"Архив": ProjectStatus.ARCHIVED, "Завершена": ProjectStatus.COMPLETED}


@given(parsers.parse("проект в статусе «{status}»"))
@aio
async def project_in_status(
    world: World, db_session: AsyncSession, scene: Scene, status: str
) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await db_session.execute(update(Project).where(Project.id == pid).values(status=STATUS[status]))
    await db_session.flush()
    scene.data |= {"pid": pid, "moderator": moderator}


@when("руководитель пресейла нажимает «Стать модератором проекта»")
@aio
async def head_joins(world: World, scene: Scene) -> None:
    head = await world.actor(SystemRole.PRESALE_HEAD)
    scene.responses["project"] = await head.get(f"/projects/{scene.data['pid']}")
    scene.responses["join"] = await head.post(f"/projects/{scene.data['pid']}/join-as-moderator")


@then("кнопка неактивна, а API возвращает 409")
def join_refused(scene: Scene) -> None:
    """Кнопку гасит интерфейс по статусу проекта (FR-PORT-03, QA-018); API отвечает 409."""
    shown = scene.responses["project"]
    assert shown.status_code == 200, shown.text
    assert shown.json().get("project", shown.json())["status"] == "archived"
    join = scene.responses["join"]
    assert (join.status_code, join.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")


@given(parsers.parse(
    "проект в статусе «Завершена» {days:d} день и срок автоархивации {limit:d}"
))  # fmt: skip
@aio
async def completed_long_ago(
    world: World, db_session: AsyncSession, scene: Scene, days: int, limit: int
) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    now = dt.datetime.now(dt.UTC)
    await db_session.execute(update(Project).where(Project.id == pid).values(
        status=ProjectStatus.COMPLETED, completed_at=now - dt.timedelta(days=days),
    ))  # fmt: skip
    await db_session.merge(SystemSetting(key="method.autoarchive_days", value=limit))
    await db_session.flush()
    scene.data |= {"pid": pid, "moderator": moderator, "now": now}


@then("проект в статусе «Архив», в ленте запись от имени «Система»")
@aio
async def archived_by_system(db_session: AsyncSession, scene: Scene) -> None:
    pid = scene.data["pid"]
    assert pid in scene.data["archived"]
    project = await db_session.get(Project, pid, populate_existing=True)
    assert project is not None
    assert project.status is ProjectStatus.ARCHIVED
    journal = (await scene.data["moderator"].get(f"/projects/{pid}/journal")).json()["items"]
    assert journal[0]["user"] is None  # «Система»
