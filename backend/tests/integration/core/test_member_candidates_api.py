"""CR-005: поиск пользователей для команды проекта — только активные, без суперадминистраторов
и аудиторов ИБ, фильтр по системной роли, без логина и почты, права team.write (FR-PRJ-01,
FR-ADM-05, BR-ROLE-02)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole, UserBlockReason, UserStatus
from estimator.db.models.users import User
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project

pytestmark = [
    pytest.mark.integration,
    pytest.mark.spec("FR-PRJ-01"),
    pytest.mark.spec("BR-ROLE-02"),
]


async def _named(db: AsyncSession, user_id: object, name: str) -> None:
    row = await db.get(User, user_id)
    row.full_name = name
    await db.flush()


async def test_candidates(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    people = {
        "Кандидат Модератор": await world.actor(SystemRole.MODERATOR),
        "Кандидат Пресейл": await world.actor(SystemRole.PRESALE),
        "Кандидат Эксперт": await world.actor(),
        "Кандидат Супер": await world.actor(SystemRole.SUPERADMIN),
        "Кандидат Аудитор": await world.actor(SystemRole.SECURITY_AUDITOR),
        "Кандидат Блок": await world.actor(),
        "Кандидат_100%": await world.actor(),
    }
    for name, actor in people.items():
        await _named(db_session, actor.id, name)
    blocked = await db_session.get(User, people["Кандидат Блок"].id)
    blocked.status, blocked.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db_session.flush()

    url = f"/projects/{pid}/member-candidates"
    found = await moderator.get(url, params={"q": "кандидат"})
    assert found.status_code == 200, found.text
    items = found.json()["items"]
    assert [i["user"]["full_name"] for i in items] == [
        "Кандидат Модератор",
        "Кандидат Пресейл",
        "Кандидат Эксперт",
        "Кандидат_100%",
    ]
    assert set(items[0]) == {"user", "system_roles"}
    assert items[0]["system_roles"] == ["moderator"]
    assert "login" not in items[0]["user"]

    only = await moderator.get(url, params={"q": "кандидат", "role": "presale"})
    assert [i["user"]["full_name"] for i in only.json()["items"]] == ["Кандидат Пресейл"]
    moderators = await moderator.get(url, params={"q": "кандидат", "role": "moderator"})
    assert [i["user"]["full_name"] for i in moderators.json()["items"]] == ["Кандидат Модератор"]
    escaped = await moderator.get(url, params={"q": "_100%"})
    assert [i["user"]["full_name"] for i in escaped.json()["items"]] == ["Кандидат_100%"]
    limited = await moderator.get(url, params={"q": "кандидат", "limit": 1})
    assert len(limited.json()["items"]) == 1

    short = await moderator.get(url, params={"q": "к"})
    assert (short.status_code, short.json()["code"]) == (422, "VALIDATION_FAILED")
    head = await world.actor(SystemRole.PRESALE_HEAD)
    assert (await head.get(url, params={"q": "кандидат"})).status_code == 403
    outsider = await world.actor(SystemRole.MODERATOR)
    assert (await outsider.get(url, params={"q": "кандидат"})).status_code == 404
