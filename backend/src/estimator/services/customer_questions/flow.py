"""Вопросы заказчику: переходы статусов, ответ, правка, снятие (CORE-044; 4.4, BR-CQ-01/02,
FR-CQ-01…03, Q-46, C-05).

Номер В-NNN выдаёт создание вопроса (CORE-040) атомарно из ``projects.next_question_no``; снятые
вопросы номер сохраняют, номера не переиспользуются.

Переходы (диаграмма 4.4); кто — проверяет gate по правам ``cq.*`` и условию ``cq_status_new``:

* ``new → sent`` — выгрузка EXP-007 или отметка вручную (:func:`mark_sent`);
* ``new``/``sent → answered`` — «Внести ответ заказчика» (пресейл, модератор);
* ``answered → closed`` — автор, модератор, пресейл; ``closed → answered`` — переоткрытие
  (модератор, пресейл);
* ``new → withdrawn`` — автор, модератор, пресейл; ``sent → withdrawn`` — модератор, пресейл.

Остальное — 409 ``INVALID_TRANSITION``. В «Архиве» статусы не меняются (M3.4-06, gate).
``threads.status``: ``resolved`` у закрытых и снятых — они не считаются открытыми вопросами.
Каждое изменение — событие ``customer_question.updated``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import CustomerQuestionStatus as Cq
from estimator.db.enums import MessageHistoryReason, MessageKind, ThreadStatus
from estimator.db.models.discussions import Message, MessageHistory, Thread
from estimator.notifications.inapp import notify
from estimator.services.common import emit
from estimator.services.discussions import feed
from estimator.services.discussions.addressees import invalid


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _expect(thread: Thread, allowed: Collection[Cq]) -> None:
    if not thread.is_customer:
        raise ApiError("INVALID_TRANSITION", detail="Это не вопрос заказчику")
    if thread.customer_status not in allowed:
        raise ApiError(
            "INVALID_TRANSITION",
            detail=f"Переход недоступен из статуса «{thread.customer_status}»",
        )


async def _publish(db: AsyncSession, thread: Thread) -> None:
    await db.flush()
    await emit(
        db,
        thread.project_id,
        "customer_question.updated",
        {
            "thread_id": str(thread.id),
            "number": thread.customer_question_no,
            "status": str(thread.customer_status),
            "sent_at": feed.ts(thread.sent_at),
            "answered_at": feed.ts(thread.answered_at),
            "closed_at": feed.ts(thread.closed_at),
            "edited_after_sent": thread.edited_after_sent,
            "withdraw_reason": thread.withdraw_reason,
        },
    )


def _set(thread: Thread, principal: Principal, status: Cq) -> None:
    thread.customer_status = status
    thread.updated_by = principal.user_id
    closed = status in (Cq.CLOSED, Cq.WITHDRAWN)
    thread.status = ThreadStatus.RESOLVED if closed else ThreadStatus.OPEN
    thread.resolved_by = principal.user_id if closed else None
    thread.resolved_at = _now() if closed else None


async def answer(db: AsyncSession, principal: Principal, thread: Thread, body: str) -> None:
    """«Внести ответ заказчика»: сообщение ``customer_answer``, статус «отвечен», уведомление."""
    _expect(thread, (Cq.NEW, Cq.SENT))
    if not body.strip():
        raise invalid("body", "ответ не может быть пустым")
    now = _now()
    message = Message(
        project_id=thread.project_id,
        node_id=thread.node_id,
        thread_id=thread.id,
        author_id=principal.user_id,
        body=body,
        kind=MessageKind.CUSTOMER_ANSWER,
        needs_answer=False,
        created_at=now,
    )
    db.add(message)
    _set(thread, principal, Cq.ANSWERED)
    thread.answered_at = now
    await db.flush()
    [out] = await feed.messages_out(db, [message])
    await emit(db, thread.project_id, "message.created", {"message": feed.ws_message(out)})
    await _publish(db, thread)
    await notify(
        db,
        "answer_to_my_question",
        [thread.opened_by],
        project_id=thread.project_id,
        node_id=thread.node_id,
        payload={
            "project_id": str(thread.project_id),
            "thread_id": str(thread.id),
            "actor_id": str(principal.user_id),
            "is_customer": True,
        }
        | ({"node_id": str(thread.node_id)} if thread.node_id else {}),
        actor_id=principal.user_id,
    )


async def close(db: AsyncSession, principal: Principal, thread: Thread) -> None:
    _expect(thread, (Cq.ANSWERED,))
    _set(thread, principal, Cq.CLOSED)
    thread.closed_by = principal.user_id
    thread.closed_at = _now()
    await _publish(db, thread)


async def reopen(db: AsyncSession, principal: Principal, thread: Thread) -> None:
    _expect(thread, (Cq.CLOSED,))
    _set(thread, principal, Cq.ANSWERED)
    thread.closed_by = None
    thread.closed_at = None
    await _publish(db, thread)


async def withdraw(db: AsyncSession, principal: Principal, thread: Thread, reason: str) -> None:
    _expect(thread, (Cq.NEW, Cq.SENT))
    if not reason.strip():
        raise invalid("reason", "укажите причину снятия")
    _set(thread, principal, Cq.WITHDRAWN)
    thread.withdraw_reason = reason.strip()
    await _publish(db, thread)


async def edit(db: AsyncSession, principal: Principal, thread: Thread, body: str) -> None:
    """Править текст вопроса: в «новом» — как правку; после «отправлен» — пометка (BR-CQ-01)."""
    _expect(thread, (Cq.NEW, Cq.SENT, Cq.ANSWERED))
    if not body.strip():
        raise invalid("body", "вопрос не может быть пустым")
    first = await db.scalar(
        select(Message)
        .where(Message.thread_id == thread.id, Message.needs_answer)
        .order_by(Message.created_at, Message.id)
        .limit(1)
    )
    if first is None:  # pragma: no cover — у вопроса всегда есть первое сообщение
        raise ApiError("NOT_FOUND")
    if first.revoked_at is not None:
        raise ApiError("INVALID_TRANSITION", detail="Сообщение вопроса отозвано")
    if body == first.body:
        return
    after_sent = thread.customer_status is not Cq.NEW
    now = _now()
    db.add(
        MessageHistory(
            message_id=first.id,
            body=first.body,
            edited_by=principal.user_id,
            edited_at=now,
            reason=MessageHistoryReason.EDIT_AFTER_SENT
            if after_sent
            else MessageHistoryReason.EDIT,
        )
    )
    first.body = body
    first.edited_at = now
    first.edited_by = principal.user_id
    if after_sent:
        thread.edited_after_sent = True
    thread.updated_by = principal.user_id
    await db.flush()
    [out] = await feed.messages_out(db, [first])
    await emit(db, thread.project_id, "message.updated", {"message": feed.ws_message(out)})
    await _publish(db, thread)


async def mark_sent(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID, thread_ids: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    """Выгруженные «новые» вопросы → «отправлен» с датой отправки (FR-CQ-02, EXP-007).

    Вопросы в других статусах и чужих проектов не трогаются; возвращает переведённые.
    """
    rows = (
        await db.scalars(
            select(Thread)
            .where(
                Thread.project_id == project_id,
                Thread.id.in_(list(thread_ids)),
                Thread.is_customer,
                Thread.customer_status == Cq.NEW,
            )
            .order_by(Thread.customer_question_no)
        )
    ).all()
    now = _now()
    for thread in rows:
        _set(thread, principal, Cq.SENT)
        thread.sent_at = now
        await _publish(db, thread)
    return [t.id for t in rows]
