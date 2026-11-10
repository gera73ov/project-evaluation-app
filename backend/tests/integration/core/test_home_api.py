"""CORE-033: «Мои оценки» — видимость по ролям и статусам, прогресс, дедлайн, «Мне», итог из
кэша, деньги только с ``money.read``, сортировка, фильтры и курсор."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from estimator.db.uuid7 import uuid7
from estimator.services.common import app_today
from estimator.services.projects import totals
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-HOME-01")]


def _by_id(body: dict) -> dict[str, dict]:
    return {i["id"]: i for i in body["items"]}


@pytest.mark.spec("FR-HOME-04")
@pytest.mark.spec("SEC-AUTHZ-05")
async def test_my_projects(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    pid = str(s.pid)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    rates = [
        {"discipline_id": str(s.backend), "rate_rub": "1000"},
        {"discipline_id": None, "rate_rub": "1000"},
    ]
    assert (
        await s.moderator.put(f"/projects/{pid}/money", json={"rates": rates})
    ).status_code == 200
    assert await totals.recompute(db_session, s.pid)

    mine = await s.moderator.get("/projects")
    assert mine.status_code == 200, mine.text
    item = _by_id(mine.json())[pid]
    assert item["my_roles"] == [{"role": "moderator", "discipline_id": None, "is_reviewer": False}]
    assert item["my_progress"] == {"done": 0, "total": 4}  # 2 фазы × 2 дисциплины
    assert (item["quote_figure"], item["quote_hours"]) == ("p80", "16.93")
    assert item["money"]["currency"] == "RUB"
    assert item["money"]["quote_cur"] is not None
    assert item["deadline_alert"] is False

    expert = _by_id((await s.backend_expert.get("/projects")).json())[pid]
    assert expert["my_roles"][0]["discipline_id"] == str(s.backend)
    assert expert["my_progress"] == {"done": 0, "total": 2}
    assert "money" not in expert
    assert expert["quote_hours"] == "16.93"

    # без TOTP в сессии денег нет и у модератора
    no_totp = await world.session_for(s.moderator.id, SystemRole.MODERATOR, mfa=False)
    assert "money" not in _by_id((await no_totp.get("/projects")).json())[pid]

    # дедлайн через 1 рабочий день, ветки не готовы — красный
    today = await app_today(db_session)
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(deadline=today + dt.timedelta(days=1))
    )
    assert _by_id((await s.backend_expert.get("/projects")).json())[pid]["deadline_alert"]

    # «Подготовка»: эксперт не видит, модератор видит; без экспертов — «команда не назначена»
    draft = await create_project(world, s.moderator)
    assert str(draft) not in _by_id((await s.backend_expert.get("/projects")).json())
    listed = _by_id((await s.moderator.get("/projects")).json())
    assert listed[str(draft)]["my_progress"] is None
    assert listed[str(draft)]["quote_hours"] is None

    # «Мне» > 0 поднимает проект наверх
    db_session.add(
        Notification(
            id=uuid7(),
            user_id=s.moderator.id,
            project_id=draft,
            kind="question_to_me",
            payload={},
        )
    )
    await db_session.flush()
    first = (await s.moderator.get("/projects")).json()["items"][0]
    assert (first["id"], first["questions_to_me"]) == (str(draft), 1)


@pytest.mark.spec("FR-HOME-02")
@pytest.mark.spec("Q-44")
async def test_filters_and_cursor(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    other = await create_project(world, s.moderator)
    await db_session.execute(
        update(Project).where(Project.id == other).values(name="Интеграция с ФНС", customer="ФНС")
    )
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ARCHIVED)
    )
    ids = set(_by_id((await s.moderator.get("/projects")).json()))
    assert str(other) in ids
    assert str(s.pid) not in ids
    archived = await s.moderator.get("/projects", params={"status": "archived"})
    assert set(_by_id(archived.json())) == {str(s.pid)}
    assert set(
        _by_id((await s.backend_expert.get("/projects", params={"status": "archived"})).json())
    ) == {str(s.pid)}

    found = await s.moderator.get("/projects", params={"q": "фнс"})
    assert set(_by_id(found.json())) == {str(other)}
    short = await s.moderator.get("/projects", params={"q": "ф"})
    assert str(other) in _by_id(short.json())  # меньше 2 символов — без поиска
    assert (await s.moderator.get("/projects", params={"role": "expert"})).json()["items"] == []

    # курсор: по одной строке
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ESTIMATION)
    )
    first = (await s.moderator.get("/projects", params={"limit": 1})).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    seen = {first["items"][0]["id"]}
    cursor = first["next_cursor"]
    while cursor:
        page = (await s.moderator.get("/projects", params={"limit": 1, "cursor": cursor})).json()
        seen |= {i["id"] for i in page["items"]}
        cursor = page["next_cursor"]
    assert {str(s.pid), str(other)} <= seen
    bad = await s.moderator.get("/projects", params={"cursor": "xyz"})
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")
    assert uuid.UUID(first["items"][0]["id"])
