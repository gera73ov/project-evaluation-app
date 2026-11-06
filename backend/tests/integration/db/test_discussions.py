"""DB-007: обсуждения, вопросы заказчику, адресаты, заметки, уведомления."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.discussions import (
    Message,
    MessageAddressee,
    MessageHistory,
    Notification,
    ProjectNote,
    Thread,
)
from estimator.db.models.users import User
from tests.integration.db.conftest import as_app
from tests.integration.db.test_tree import item, tree
from tests.integration.db.test_users_constraints import _rejects

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.2")]


async def _user(session: AsyncSession, login: str = "d.expert") -> User:
    user = User(login=login, full_name="Эксперт", status="active")
    session.add(user)
    await session.flush()
    return user


def _question(project_id, user_id, no: int, **kw: object) -> Thread:
    fields = {"is_customer": True, "customer_question_no": no, "customer_status": "new", **kw}
    return Thread(project_id=project_id, opened_by=user_id, **fields)


@pytest.mark.spec("FR-CQ-02")
async def test_customer_question_number_unique_in_project(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    other, _, _ = await tree(db_session)
    db_session.add_all(
        [
            _question(project.id, user.id, 1),
            _question(other.id, user.id, 1),  # в другом проекте — можно
            Thread(project_id=project.id, opened_by=user.id),  # обычные вопросы без номера
            Thread(project_id=project.id, opened_by=user.id),
        ]
    )
    await db_session.flush()
    await _rejects(db_session, _question(project.id, user.id, 1))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"is_customer": True},  # без номера и статуса
        {"customer_question_no": 3},  # номер у обычного вопроса
        {"customer_status": "new"},
    ],
    ids=["customer-no-number", "number-not-customer", "status-not-customer"],
)
async def test_thread_customer_fields_consistent(db_session: AsyncSession, kwargs: dict) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    await _rejects(db_session, Thread(project_id=project.id, opened_by=user.id, **kwargs))


async def test_withdrawn_requires_reason(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    await _rejects(db_session, _question(project.id, user.id, 1, customer_status="withdrawn"))


@pytest.mark.spec("FR-DISC-02")
@pytest.mark.parametrize(
    ("kind", "body", "event", "ok"),
    [
        ("message", "x" * 4000, None, True),
        ("message", "x" * 4001, None, False),
        ("message", "", None, False),
        ("customer_answer", "x" * 10000, None, True),
        ("event", "", {"action": "update", "changes": {}}, True),
        ("event", "", None, False),  # событие без структуры
        ("message", "текст", {"action": "update"}, False),  # структура у обычного сообщения
    ],
    ids=["4000", "4001", "empty", "answer-10000", "event", "event-no-json", "message-json"],
)
async def test_message_body_limits(
    db_session: AsyncSession, kind: str, body: str, event: dict | None, ok: bool
) -> None:
    user = await _user(db_session)
    project, _, branch = await tree(db_session)
    message = Message(
        project_id=project.id,
        node_id=branch.id,
        author_id=user.id,
        kind=kind,
        body=body,
        event=event,
    )
    if ok:
        db_session.add(message)
        await db_session.flush()
    else:
        await _rejects(db_session, message)


async def test_addressees(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    message = Message(project_id=project.id, author_id=user.id, body="Вопрос")
    db_session.add(message)
    await db_session.flush()
    db_session.add_all(
        [
            MessageAddressee(message_id=message.id, target_type="moderators"),
            MessageAddressee(message_id=message.id, target_type="user", target_id=user.id),
        ]
    )
    await db_session.flush()
    # «модераторы» дважды — NULLS NOT DISTINCT; пользователь без id; id у «заказчика»
    for bad in (
        {"target_type": "moderators"},
        {"target_type": "discipline"},
        {"target_type": "customer", "target_id": user.id},
    ):
        await _rejects(db_session, MessageAddressee(message_id=message.id, **bad))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE message_history SET body = 'x'",
        "DELETE FROM message_history",
        "TRUNCATE message_history",
    ],
    ids=["update", "delete", "truncate"],
)
@pytest.mark.spec("SEC-AUD-03")
async def test_message_history_insert_only(db_session: AsyncSession, statement: str) -> None:
    user = await _user(db_session)
    await as_app(db_session)
    project, _, _ = await tree(db_session)
    message = Message(project_id=project.id, author_id=user.id, body="Было")
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        MessageHistory(message_id=message.id, body="Было", edited_by=user.id, reason="edit")
    )
    await db_session.flush()
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_node_delete_cascades_and_nulls_notifications(db_session: AsyncSession) -> None:
    """Физическое удаление узла (очистка корзины ролью приложения) чистит ленту узла."""
    user = await _user(db_session)
    await as_app(db_session)
    project, _, branch = await tree(db_session)
    leaf = item(branch)
    db_session.add(leaf)
    await db_session.flush()
    thread = Thread(project_id=project.id, node_id=leaf.id, opened_by=user.id)
    db_session.add(thread)
    await db_session.flush()
    message = Message(
        project_id=project.id, node_id=leaf.id, thread_id=thread.id, author_id=user.id, body="?"
    )
    db_session.add(message)
    await db_session.flush()
    notification = Notification(
        user_id=user.id, project_id=project.id, node_id=leaf.id, kind="question.new"
    )
    db_session.add_all(
        [
            MessageHistory(message_id=message.id, body="?", edited_by=user.id, reason="edit"),
            ProjectNote(project_id=project.id, node_id=leaf.id, author_id=user.id, body="Заметка"),
            notification,
        ]
    )
    await db_session.flush()
    await db_session.delete(leaf)
    await db_session.flush()
    for model in (Thread, Message, MessageHistory, ProjectNote):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__
    await db_session.refresh(notification)
    assert notification.node_id is None


async def test_note_body_required(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    await _rejects(db_session, ProjectNote(project_id=project.id, author_id=user.id, body=""))
