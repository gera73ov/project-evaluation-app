"""CORE-041…043: «Решено» и «Переоткрыть», вывод в комментарий, правка и отзыв сообщения,
``message_history``, серые события в ленте и переадресация вопросов."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import CommentTag
from estimator.db.models.discussions import MessageHistory
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.discussions import events as feed_events
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import _patch, _setup
from tests.integration.core.test_structure_api import _leaf, _move

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-DISC-05")]


@pytest.mark.spec("FR-DISC-09")
async def test_resolve_and_reopen(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    asked = await s.backend_expert.post(
        f"/nodes/{leaf['id']}/messages",
        json={
            "body": "Нужен SSO?",
            "needs_answer": True,
            "addressees": [{"target_type": "user", "target_id": str(s.moderator.id)}],
        },
    )
    thread_id = asked.json()["thread_id"]
    resolve = f"/threads/{thread_id}/resolve"

    # не автор и не адресат эксперт → 403
    denied = await s.frontend_expert.post(resolve, json={})
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")

    tag = (await db_session.scalars(select(CommentTag.id))).first()
    done = await s.moderator.post(
        resolve, json={"conclusion": {"text": "  SSO не нужен ", "tag_id": str(tag)}}
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["resolved_by"]["id"]) == ("resolved", str(s.moderator.id))
    tree = (await s.moderator.get(f"/projects/{s.pid}/tree")).json()
    node = next(n for n in tree["nodes"] if n["id"] == leaf["id"])
    assert node["comment_lines"] == [{"tag_id": str(tag), "text": "SSO не нужен"}]
    assert (node["open_questions"], node["questions_to_me"]) == (0, 0)

    again = await s.moderator.post(resolve)
    assert (again.status_code, again.json()["code"]) == (409, "INVALID_TRANSITION")

    reopened = await s.backend_expert.post(f"/threads/{thread_id}/reopen")
    assert reopened.status_code == 200, reopened.text
    assert (reopened.json()["status"], reopened.json()["resolved_at"]) == ("open", None)
    twice = await s.backend_expert.post(f"/threads/{thread_id}/reopen")
    assert twice.status_code == 409

    await deliver_events(db_session)
    names = [e["event"] for e in events.on(f"project:{s.pid}")]
    assert "thread.resolved" in names
    assert names[-1] == "thread.reopened"

    # вывод — только у вопроса узла
    top = await s.moderator.post(
        f"/projects/{s.pid}/threads", json={"node_id": None, "body": "Срок?"}
    )
    bad = await s.moderator.post(
        f"/threads/{top.json()['id']}/resolve",
        json={"conclusion": {"text": "x", "tag_id": None}},
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "VALIDATION_FAILED")


@pytest.mark.spec("FR-DISC-06")
async def test_edit_and_revoke(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    s = await _setup(world, db_session)
    url = f"/projects/{s.pid}/messages"
    mine = (await s.backend_expert.post(url, json={"body": "Черновик"})).json()

    other = await s.frontend_expert.patch(f"/messages/{mine['id']}", json={"body": "Чужое"})
    assert (other.status_code, other.json()["code"]) == (403, "FORBIDDEN")

    edited = await s.backend_expert.patch(f"/messages/{mine['id']}", json={"body": "Итог"})
    assert edited.status_code == 200, edited.text
    assert (edited.json()["body"], edited.json()["edited_at"] is not None) == ("Итог", True)

    # после ответа — 409, отзыв доступен
    await s.moderator.post(url, json={"body": "Принято"})
    late = await s.backend_expert.patch(f"/messages/{mine['id']}", json={"body": "Иначе"})
    assert (late.status_code, late.json()["code"]) == (409, "MESSAGE_HAS_REPLIES")
    revoked = await s.backend_expert.post(f"/messages/{mine['id']}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert (revoked.json()["body"], revoked.json()["revoked"]) == ("", True)
    assert (await s.backend_expert.post(f"/messages/{mine['id']}/revoke")).status_code == 200

    history = (
        await db_session.scalars(
            select(MessageHistory)
            .where(MessageHistory.message_id == mine["id"])
            .order_by(MessageHistory.edited_at)
        )
    ).all()
    assert [(h.body, str(h.reason)) for h in history] == [
        ("Черновик", "edit"),
        ("Итог", "revoke"),
    ]
    # исходный текст — модератору, эксперту нет (CR-012)
    seen = await s.moderator.get(f"/messages/{mine['id']}/history")
    assert seen.status_code == 200, seen.text
    assert [(h["body"], h["reason"]) for h in seen.json()["items"]] == [
        ("Итог", "revoke"),
        ("Черновик", "edit"),
    ]
    hidden = await s.backend_expert.get(f"/messages/{mine['id']}/history")
    assert (hidden.status_code, hidden.json()["code"]) == (403, "FORBIDDEN")
    feed = (await s.frontend_expert.get(url)).json()["items"]
    assert next(m for m in feed if m["id"] == mine["id"])["body"] == ""

    await deliver_events(db_session)
    updated = [e for e in events.on(f"project:{s.pid}") if e["event"] == "message.updated"]
    assert "body" not in updated[-1]["data"]["message"]
    assert updated[-1]["data"]["message"]["revoked_at"]


@pytest.mark.spec("FR-DISC-07")
@pytest.mark.spec("FR-ADM-05")
async def test_feed_events(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    quiet = await _leaf(s.backend_expert, s, branch.id, "Тихий", o="1", r="2", p="3")
    talk = await _leaf(s.backend_expert, s, branch.id, "Обсуждаемый", o="8", r="12", p="20")
    assert (
        await s.moderator.post(f"/nodes/{talk['id']}/messages", json={"body": "?"})
    ).status_code == 201

    assert (await _patch(s.backend_expert, quiet["id"], quiet["version"], o="2")).status_code == 200
    changed = await _patch(s.backend_expert, talk["id"], talk["version"], o="10", p="30")
    assert changed.status_code == 200, changed.text
    assert (
        await _move(s.backend_expert, db_session, talk["id"], branch.id, quiet["id"])
    ).status_code == 200

    assert (await s.moderator.get(f"/nodes/{quiet['id']}/messages")).json()["items"] == []
    items = (await s.moderator.get(f"/nodes/{talk['id']}/messages")).json()["items"]
    assert [m["kind"] for m in items] == ["event", "event", "message"]
    moved, edit = items[0]["event"], items[1]["event"]
    assert edit == {"type": "node_changed", "changes": {"o": ["8", "10"], "p": ["20", "30"]}}
    assert moved["type"] == "node_moved"
    assert items[1]["author"]["id"] == str(s.backend_expert.id)
    tree = (await s.moderator.get(f"/projects/{s.pid}/tree")).json()
    assert next(n for n in tree["nodes"] if n["id"] == talk["id"])["messages_count"] == 3

    # переадресация открытых вопросов (API для ADM-012)
    asked = await s.backend_expert.post(
        f"/nodes/{talk['id']}/messages",
        json={
            "body": "Кто?",
            "needs_answer": True,
            "addressees": [{"target_type": "user", "target_id": str(s.frontend_expert.id)}],
        },
    )
    thread_id = asked.json()["thread_id"]
    redirected = await feed_events.redirect_questions(
        db_session, s.pid, s.frontend_expert.id, s.moderator.id, s.moderator.id
    )
    assert [str(t) for t in redirected] == [thread_id]
    [thread] = (await s.moderator.get(f"/projects/{s.pid}/threads")).json()["items"]
    assert thread["first_message"]["addressees"] == [
        {"target_type": "user", "target_id": str(s.moderator.id)}
    ]
    assert thread["replies_count"] == 0
    last = (await s.moderator.get(f"/nodes/{talk['id']}/messages")).json()["items"][0]
    assert last["event"]["type"] == "question_redirected"
    assert last["event"]["to"]["id"] == str(s.moderator.id)
