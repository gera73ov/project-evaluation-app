"""Серые события в ленте обсуждения (CORE-043; FR-DISC-07, FR-TREE-34, BR-BR-02, FR-ADM-05).

Запись ``kind = event``: ``body = ""``, структура — в ``messages.event``, автор — кто сделал
изменение. Текст «И. Иванов изменил O/R/P 8–12–20 → 12–16–30 · 03.11 14:20» собирает клиент из
``event`` и ``created_at``. Формы ``event``:

* ``{"type": "node_changed", "changes": {"o": [old, new], …}}`` — поля ``o``, ``r``, ``p``,
  ``multiplier``, ``comment_lines``, ``type_id`` (значения — как в истории узла: часы строкой,
  uuid строкой);
* ``{"type": "node_moved", "changes": {"parent": [old, new]}}``;
* ``{"type": "question_redirected", "thread_id", "from": UserRef, "to": UserRef}``.

Событие изменения узла пишется, только если у узла есть хотя бы одно сообщение (не событие):
иначе лента состояла бы из одних событий, а изменение и так лежит в истории узла. Каждое событие
публикуется как ``message.created`` со своей версией проекта.

:func:`add_event` и :func:`redirect_questions` — API для других сервисов (ADM-012).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.enums import AddresseeType, MessageKind, ThreadStatus
from estimator.db.models.discussions import Message, MessageAddressee, Thread
from estimator.services.common import emit
from estimator.services.discussions import feed

#: Поля узла, правка которых даёт событие в ленте (FR-DISC-07); название — только в истории.
FEED_FIELDS = ("o", "r", "p", "multiplier", "comment_lines", "type_id")


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


async def has_messages(db: AsyncSession, node_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(exists().where(Message.node_id == node_id, Message.kind != MessageKind.EVENT))
        )
    )


async def add_event(
    db: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    event: Mapping[str, Any],
    *,
    thread_id: uuid.UUID | None = None,
) -> Message:
    """Серая запись в ленте узла (``node_id``) или проекта и событие ``message.created``."""
    message = Message(
        project_id=project_id,
        node_id=node_id,
        thread_id=thread_id,
        author_id=actor_id,
        body="",
        kind=MessageKind.EVENT,
        event=dict(event),
        needs_answer=False,
        created_at=dt.datetime.now(dt.UTC),
    )
    db.add(message)
    await db.flush()
    [out] = await feed.messages_out(db, [message])
    await emit(db, project_id, "message.created", {"message": feed.ws_message(out)})
    return message


async def node_changed(
    db: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    actor_id: uuid.UUID,
    kind: str,
    changes: Mapping[str, tuple[Any, Any]],
) -> Message | None:
    """Событие правки (``node_changed``) или переноса (``node_moved``) узла с сообщениями."""
    if not changes or not await has_messages(db, node_id):
        return None
    event = {
        "type": kind,
        "changes": {k: [_plain(old), _plain(new)] for k, (old, new) in changes.items()},
    }
    return await add_event(db, project_id, node_id, actor_id, event)


def feed_changes(diff: Mapping[str, tuple[Any, Any]]) -> dict[str, tuple[Any, Any]]:
    return {k: v for k, v in diff.items() if k in FEED_FIELDS}


async def redirect_questions(
    db: AsyncSession,
    project_id: uuid.UUID,
    from_user: uuid.UUID,
    to_user: uuid.UUID,
    actor_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Открытые вопросы проекта, адресованные ``from_user``, — адресовать ``to_user`` (FR-ADM-05).

    Решённые вопросы не трогаются. В ленту каждого вопроса — событие «вопрос переадресован»;
    возвращает переадресованные вопросы (для уведомления ``question_redirected``).
    """
    rows = (
        await db.execute(
            select(Thread.id, Thread.node_id, Message.id)
            .join(Message, and_(Message.thread_id == Thread.id, Message.needs_answer))
            .join(MessageAddressee, MessageAddressee.message_id == Message.id)
            .where(
                Thread.project_id == project_id,
                Thread.status == ThreadStatus.OPEN,
                MessageAddressee.target_type == AddresseeType.USER,
                MessageAddressee.target_id == from_user,
            )
            .order_by(Thread.created_at, Thread.id)
        )
    ).all()
    if not rows:
        return []
    message_ids = [m for _, _, m in rows]
    taken = set(
        (
            await db.scalars(
                select(MessageAddressee.message_id).where(
                    MessageAddressee.message_id.in_(message_ids),
                    MessageAddressee.target_type == AddresseeType.USER,
                    MessageAddressee.target_id == to_user,
                )
            )
        ).all()
    )
    for mid in message_ids:
        where = (
            MessageAddressee.message_id == mid,
            MessageAddressee.target_type == AddresseeType.USER,
            MessageAddressee.target_id == from_user,
        )
        if mid in taken:  # замена уже среди адресатов — только убрать исходного
            await db.execute(MessageAddressee.__table__.delete().where(*where))
        else:
            await db.execute(update(MessageAddressee).where(*where).values(target_id=to_user))
    refs = await feed.user_refs(db, [from_user, to_user])
    for thread_id, node_id, _ in rows:
        await add_event(
            db,
            project_id,
            node_id,
            actor_id,
            {
                "type": "question_redirected",
                "thread_id": str(thread_id),
                "from": refs[from_user],
                "to": refs[to_user],
            },
            thread_id=thread_id,
        )
    return [t for t, _, _ in rows]
