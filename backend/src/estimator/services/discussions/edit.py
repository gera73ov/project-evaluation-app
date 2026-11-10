"""Правка и отзыв сообщения (CORE-042; FR-DISC-06, 14.2 ``message_history``).

* Править и отзывать может только автор (иначе 403 ``FORBIDDEN``); удалить нельзя.
* Правка — пока на сообщение не ответили, иначе 409 ``MESSAGE_HAS_REPLIES``. Ответом считается
  более позднее сообщение другого автора: в вопросе — в этом же вопросе, у сообщения без
  вопроса — в той же ленте (узла или проекта). Серые события ответами не считаются.
* Вопрос заказчику после «отправлен» автор не правит (403, BR-CQ-01); правку модератором и
  пресейлом делает CORE-044.
* Прежний текст каждой правки и отзыва пишется в ``message_history`` (только INSERT); отзыв
  скрывает текст в выдаче, повторный отзыв ничего не меняет.
* Событие ``message.updated`` — со своей версией проекта.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import CustomerQuestionStatus, MessageHistoryReason, MessageKind
from estimator.db.models.discussions import Message, MessageHistory, Thread
from estimator.services.common import emit
from estimator.services.discussions import feed
from estimator.services.discussions.addressees import invalid


async def _own(db: AsyncSession, principal: Principal, message: Message) -> None:
    if message.author_id != principal.user_id or message.kind is not MessageKind.MESSAGE:
        raise ApiError("FORBIDDEN", detail="Править и отзывать можно только своё сообщение")


async def has_replies(db: AsyncSession, message: Message) -> bool:
    later = (
        Message.id != message.id,
        Message.kind != MessageKind.EVENT,
        Message.author_id.is_distinct_from(message.author_id),
        Message.created_at >= message.created_at,
        Message.project_id == message.project_id,
    )
    if message.thread_id is not None:
        where = (*later, Message.thread_id == message.thread_id)
    elif message.node_id is not None:
        where = (*later, Message.node_id == message.node_id)
    else:
        where = (*later, Message.node_id.is_(None))
    return bool(await db.scalar(select(exists().where(*where))))


async def _publish(db: AsyncSession, message: Message) -> dict[str, Any]:
    await db.flush()
    [out] = await feed.messages_out(db, [message])
    await emit(
        db,
        message.project_id,
        "message.updated",
        {"message": feed.ws_message(out, message.revoked_at)},
    )
    return out


async def edit(
    db: AsyncSession, principal: Principal, message: Message, body: str
) -> dict[str, Any]:
    await _own(db, principal, message)
    if message.revoked_at is not None:
        raise ApiError("FORBIDDEN", detail="Отозванное сообщение не правят")
    if not body.strip():
        raise invalid("body", "сообщение не может быть пустым")
    if message.thread_id is not None and message.needs_answer:
        thread = await db.get(Thread, message.thread_id)
        if (
            thread is not None
            and thread.is_customer
            and (thread.customer_status is not CustomerQuestionStatus.NEW)
        ):
            raise ApiError("FORBIDDEN", detail="После отправки заказчику текст не меняют")
    if await has_replies(db, message):
        raise ApiError("MESSAGE_HAS_REPLIES")
    if body == message.body:
        [out] = await feed.messages_out(db, [message])
        return out
    now = dt.datetime.now(dt.UTC)
    db.add(
        MessageHistory(
            message_id=message.id,
            body=message.body,
            edited_by=principal.user_id,
            edited_at=now,
            reason=MessageHistoryReason.EDIT,
        )
    )
    message.body = body
    message.edited_at = now
    message.edited_by = principal.user_id
    return await _publish(db, message)


async def revoke(db: AsyncSession, principal: Principal, message: Message) -> dict[str, Any]:
    await _own(db, principal, message)
    if message.revoked_at is not None:
        [out] = await feed.messages_out(db, [message])
        return out
    now = dt.datetime.now(dt.UTC)
    db.add(
        MessageHistory(
            message_id=message.id,
            body=message.body,
            edited_by=principal.user_id,
            edited_at=now,
            reason=MessageHistoryReason.REVOKE,
        )
    )
    message.revoked_at = now
    return await _publish(db, message)


async def history(db: AsyncSession, message: Message) -> list[dict[str, Any]]:
    """Прежние тексты сообщения от новых к старым (CR-012; только модератору — gate)."""
    rows = (
        await db.scalars(
            select(MessageHistory)
            .where(MessageHistory.message_id == message.id)
            .order_by(MessageHistory.edited_at.desc(), MessageHistory.id.desc())
        )
    ).all()
    users = await feed.user_refs(db, (h.edited_by for h in rows))
    return [
        {
            "body": h.body,
            "edited_by": users[h.edited_by],
            "edited_at": feed.ts(h.edited_at),
            "reason": str(h.reason),
        }
        for h in rows
    ]
