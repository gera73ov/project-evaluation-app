"""CORE-040: ленты узла и проекта, вопросы и ответы, адресаты и правило по умолчанию, счётчики
в дереве, права по статусу проекта, лимит 60 сообщений в минуту, уведомления и события."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from estimator.realtime.bus.memory import InMemoryBus
from estimator.security.ratelimit.limiter import LIMITS, Limit
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import Setup, _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-DISC-01")]


async def _kinds(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await db.scalars(
        select(Notification.kind).where(Notification.user_id == user_id).order_by(Notification.id)
    )
    return list(rows)


async def _tree_node(actor, s: Setup, node_id: str) -> dict:  # type: ignore[no-untyped-def]
    tree = (await actor.get(f"/projects/{s.pid}/tree")).json()
    return next(n for n in tree["nodes"] if n["id"] == node_id) | {"_tree": tree}


@pytest.mark.spec("FR-DISC-03")
@pytest.mark.spec("FR-DISC-04")
@pytest.mark.spec("FR-DISC-09")
async def test_question_flow(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    url = f"/nodes/{leaf['id']}/messages"

    plain = await s.backend_expert.post(url, json={"body": "Берём <b>OAuth</b>?"})
    assert plain.status_code == 201, plain.text
    assert (plain.json()["thread_id"], plain.json()["body"]) == (None, "Берём <b>OAuth</b>?")

    # флаг без адресата внутри ветки — эксперты дисциплины
    asked = await s.moderator.post(url, json={"body": "Нужен SSO?", "needs_answer": True})
    assert asked.status_code == 201, asked.text
    question = asked.json()
    assert question["needs_answer"] is True
    assert question["addressees"] == [{"target_type": "discipline", "target_id": str(s.backend)}]
    thread_id = question["thread_id"]
    assert thread_id

    mine = await _tree_node(s.backend_expert, s, leaf["id"])
    assert (mine["messages_count"], mine["open_questions"], mine["questions_to_me"]) == (2, 1, 1)
    status = next(
        b
        for b in mine["_tree"]["branch_statuses"]
        if (b["phase_id"], b["discipline_id"]) == (str(branch.phase_id), str(s.backend))
    )
    assert status["open_questions"] == 1
    other = await _tree_node(s.frontend_expert, s, leaf["id"])
    assert (other["open_questions"], other["questions_to_me"]) == (1, 0)
    assert "question_to_me" in await _kinds(db_session, s.backend_expert.id)
    assert "question_to_me" not in await _kinds(db_session, s.frontend_expert.id)

    await deliver_events(db_session)
    names = [e["event"] for e in events.on(f"project:{s.pid}")]
    assert names[-3:] == ["message.created", "thread.created", "message.created"]
    created = next(e for e in events.on(f"project:{s.pid}") if e["event"] == "thread.created")
    assert created["data"]["thread"]["opened_by"] == str(s.moderator.id)

    reply = await s.backend_expert.post(f"/threads/{thread_id}/messages", json={"body": "Да"})
    assert reply.status_code == 201, reply.text
    assert (reply.json()["thread_id"], reply.json()["needs_answer"]) == (thread_id, False)
    assert reply.json()["node_id"] == leaf["id"]
    assert "answer_to_my_question" in await _kinds(db_session, s.moderator.id)

    # лента: от новых к старым, «последние 3», курсор
    feed = (await s.frontend_expert.get(url, params={"limit": 3})).json()
    assert [m["body"] for m in feed["items"]] == ["Да", "Нужен SSO?", "Берём <b>OAuth</b>?"]
    assert feed["next_cursor"] is None
    [thread] = feed["threads"]
    assert (thread["replies_count"], thread["first_message"]["body"]) == (1, "Нужен SSO?")
    assert thread["opened_by"]["id"] == str(s.moderator.id)
    first = (await s.moderator.get(url, params={"limit": 2})).json()
    assert first["next_cursor"]
    rest = (await s.moderator.get(url, params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert [m["body"] for m in rest["items"]] == ["Берём <b>OAuth</b>?"]
    bad = await s.moderator.get(
        f"/projects/{s.pid}/messages", params={"cursor": first["next_cursor"]}
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")

    # вопрос уровня проекта — модераторам; в ленте узла его нет
    top = await s.backend_expert.post(
        f"/projects/{s.pid}/threads", json={"node_id": None, "body": "Срок сдачи?"}
    )
    assert top.status_code == 201, top.text
    assert top.json()["first_message"]["addressees"] == [
        {"target_type": "moderators", "target_id": None}
    ]
    project_feed = (await s.moderator.get(f"/projects/{s.pid}/messages")).json()
    assert [m["body"] for m in project_feed["items"]] == ["Срок сдачи?"]
    assert len(project_feed["threads"]) == 1

    threads = f"/projects/{s.pid}/threads"
    to_me = (await s.moderator.get(threads, params={"addressee": "me"})).json()["items"]
    assert [t["id"] for t in to_me] == [top.json()["id"]]
    by_disc = (await s.moderator.get(threads, params={"discipline_id": str(s.backend)})).json()
    assert [t["id"] for t in by_disc["items"]] == [thread_id]
    level = (await s.moderator.get(threads, params={"project_level": "true"})).json()
    assert [t["id"] for t in level["items"]] == [top.json()["id"]]
    assert (await s.moderator.get(threads, params={"status": "resolved"})).json()["items"] == []
    paged = (await s.moderator.get(threads, params={"limit": 1})).json()
    assert len(paged["items"]) == 1
    assert paged["next_cursor"]


@pytest.mark.spec("FR-DISC-03")
@pytest.mark.spec("FR-CQ-01")
async def test_addressees_and_customer(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    presale = await world.actor(SystemRole.PRESALE)
    team = [
        {"user_id": str(s.moderator.id), "role": "moderator"},
        {"user_id": str(s.backend_expert.id), "role": "expert", "discipline_id": str(s.backend)},
        {"user_id": str(s.frontend_expert.id), "role": "expert", "discipline_id": str(s.frontend)},
        {"user_id": str(presale.id), "role": "presale"},
    ]
    put = await s.moderator.put(f"/projects/{s.pid}/members", json={"members": team})
    assert put.status_code == 200, put.text
    url = f"/projects/{s.pid}/threads"

    first = await s.backend_expert.post(
        url,
        json={
            "node_id": None,
            "body": "Какие SLA?",
            "addressees": [
                {"target_type": "customer", "target_id": None},
                {"target_type": "user", "target_id": str(s.frontend_expert.id)},
            ],
        },
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert (body["is_customer"], body["customer_status"], body["customer_question_no"]) == (
        True,
        "new",
        1,
    )
    assert "question_to_me" in await _kinds(db_session, presale.id)
    assert "question_to_me" in await _kinds(db_session, s.frontend_expert.id)
    assert "question_to_me" not in await _kinds(db_session, s.moderator.id)  # пресейл есть

    # @заказчик в обычном сообщении сам ставит «нужен ответ»; номер растёт
    second = await s.moderator.post(
        f"/projects/{s.pid}/messages",
        json={"body": "Бюджет?", "addressees": [{"target_type": "customer", "target_id": None}]},
    )
    assert second.status_code == 201, second.text
    assert second.json()["needs_answer"] is True
    listed = (await presale.get(url, params={"addressee": "me"})).json()["items"]
    assert sorted(t["customer_question_no"] for t in listed) == [1, 2]

    async def code(payload: dict) -> tuple[int, str]:
        r = await s.backend_expert.post(url, json={"node_id": None} | payload)
        return r.status_code, r.json().get("code")

    stranger = await world.actor()
    bad = [
        {"body": "  \n "},
        {"body": "x", "addressees": [{"target_type": "user", "target_id": str(stranger.id)}]},
        {
            "body": "x",
            "addressees": [{"target_type": "discipline", "target_id": str(uuid.uuid4())}],
        },
        {"body": "x", "addressees": [{"target_type": "moderators", "target_id": str(s.backend)}]},
        {"body": "x", "node_id": str(uuid.uuid4())},
        {"body": "x" * 4001},
    ]
    for payload in bad:
        assert await code(payload) == (422, "VALIDATION_FAILED"), payload

    suggest = f"/projects/{s.pid}/members/suggest"
    found = (await s.backend_expert.get(suggest, params={"q": "@бэк"})).json()["items"]
    assert found == [{"target_type": "discipline", "target_id": str(s.backend), "label": "Бэкенд"}]
    labels = {
        i["label"] for i in (await s.moderator.get(suggest, params={"q": "за"})).json()["items"]
    }
    assert "заказчик" in labels
    everyone = (await s.moderator.get(suggest, params={"q": ""})).json()["items"]
    assert {i["target_type"] for i in everyone} == {"discipline", "user", "moderators", "customer"}
    outsider = await world.actor(SystemRole.MODERATOR)
    assert (await outsider.get(suggest, params={"q": "б"})).status_code in (403, 404)


@pytest.mark.spec("SEC-WEB-07")
async def test_status_rights_and_limit(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session, launch=False)
    url = f"/projects/{s.pid}/messages"
    # «Подготовка»: пишут только модераторы; эксперт проект ещё не видит
    denied = await s.backend_expert.post(url, json={"body": "Привет"})
    assert denied.status_code == 404, denied.text
    assert (await s.moderator.post(url, json={"body": "Привет"})).status_code == 201

    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.COMPLETED)
    )
    closed = await s.moderator.post(url, json={"body": "Ещё"})
    assert (closed.status_code, closed.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")
    assert (await s.backend_expert.get(url)).status_code == 200  # «Завершена» — чтение

    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ESTIMATION)
    )
    monkeypatch.setitem(LIMITS, "messages", Limit("messages", 2, 60))
    for _ in range(2):
        assert (await s.backend_expert.post(url, json={"body": "ok"})).status_code == 201
    limited = await s.backend_expert.post(url, json={"body": "ok"})
    assert (limited.status_code, limited.json()["code"]) == (429, "RATE_LIMITED")
    assert (await s.frontend_expert.post(url, json={"body": "ok"})).status_code == 201
