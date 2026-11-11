"""QA-015 · шаги сценария замены участника (SPEC 17.2): G-20 «Вопросы переходят к замене»."""

from __future__ import annotations

from pytest_bdd import given, parsers, then, when
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import UserBlockReason, UserStatus
from estimator.db.models.users import User
from tests.acceptance.steps.common import Scene, aio
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

#: Сокращение из сценария → ФИО учётки («Н. Новиков» — «Новиков Николай»).
PEOPLE = {
    "Н. Новиков": "Новиков Николай",
    "И. Иванов": "Иванов Иван",
    "И. Иванову": "Иванов Иван",
    "И. Иванова": "Иванов Иван",
}  # падежи из текста сценария


def short(full_name: str) -> str:
    """«Фамилия Имя» → «И. Фамилия», как имя показывает лента."""
    last, first = full_name.split()[:2]
    return f"{first[0]}. {last}"


async def _named(world: World, db: AsyncSession, full_name: str):  # type: ignore[no-untyped-def]
    actor = await world.actor()
    user = await db.get(User, actor.id)
    assert user is not None
    user.full_name = full_name
    await db.flush()
    return actor


@given(parsers.parse("{who} заблокирован, ему адресован открытый вопрос в «Портале дилеров»"))
@aio
async def blocked_addressee(world: World, db_session: AsyncSession, scene: Scene, who: str) -> None:
    s = scene.s = await _setup(world, db_session)
    gone = await _named(world, db_session, PEOPLE[who])
    team = (await s.moderator.get(f"/projects/{s.pid}/members")).json()["items"]
    members = [{"user_id": m["user"]["id"], "role": m["role"],
                "discipline_id": m["discipline_id"]} for m in team]  # fmt: skip
    members.append({"user_id": str(gone.id), "role": "expert", "discipline_id": str(s.backend)})
    assert (
        await s.moderator.put(f"/projects/{s.pid}/members", json={"members": members})
    ).status_code == 200
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Обмен с 1С", o="8", r="12", p="20")
    asked = await s.moderator.post(f"/nodes/{leaf['id']}/messages", json={
        "body": "Какой протокол?", "needs_answer": True,
        "addressees": [{"target_type": "user", "target_id": str(gone.id)}],
    })  # fmt: skip
    assert asked.status_code == 201, asked.text
    user = await db_session.get(User, gone.id)
    assert user is not None
    user.status, user.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db_session.flush()
    scene.data |= {"gone": gone, "leaf": leaf["id"], "thread": asked.json()["thread_id"]}


@when(parsers.parse("модератор заменяет Новикова на {who}"))
@aio
async def replace_member(world: World, db_session: AsyncSession, scene: Scene, who: str) -> None:
    s = scene.s
    heir = await _named(world, db_session, PEOPLE[who])
    replaced = await s.moderator.post(
        f"/projects/{s.pid}/members/{scene.data['gone'].id}/replace",
        json={"replacement_user_id": str(heir.id)},
    )
    assert replaced.status_code == 200, replaced.text
    scene.data["heir"] = heir


@then(parsers.parse("открытый вопрос адресован {who}"))
@aio
async def question_readdressed(scene: Scene, who: str) -> None:
    s = scene.s
    threads = (await s.moderator.get(f"/projects/{s.pid}/threads")).json()["items"]
    [thread] = [t for t in threads if t["id"] == scene.data["thread"]]
    assert thread["first_message"]["addressees"] == [
        {"target_type": "user", "target_id": str(scene.data["heir"].id)}
    ]
    assert PEOPLE[who] == "Иванов Иван"


@then(parsers.parse("в ленте узла событие «вопрос переадресован: {source} → {target}»"))
@aio
async def feed_event(scene: Scene, source: str, target: str) -> None:
    s = scene.s
    items = (await s.moderator.get(f"/nodes/{scene.data['leaf']}/messages")).json()["items"]
    [event] = [i["event"] for i in items
               if i["kind"] == "event" and i["event"]["type"] == "question_redirected"]  # fmt: skip
    assert (short(event["from"]["full_name"]), short(event["to"]["full_name"])) == (source, target)
    assert event["to"]["id"] == str(scene.data["heir"].id)
