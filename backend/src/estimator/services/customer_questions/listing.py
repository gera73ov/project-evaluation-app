"""Список «Вопросы заказчику» (CORE-044; FR-CQ-02, 11.11): номер, текст, путь узла, автор, даты,
статус, последний ответ заказчика. Фильтры — статус и дисциплина узла; порядок — по номеру
В-NNN, курсор — номер последней строки."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import CustomerQuestionStatus, MessageKind
from estimator.db.models.discussions import Message, Thread
from estimator.db.models.tree import Node
from estimator.services.discussions import feed


async def node_paths(
    db: AsyncSession, project_id: uuid.UUID, node_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Путь «фаза → дисциплина → … → узел» по названиям (удалённые узлы тоже: путь на момент)."""
    if not node_ids:
        return {}
    rows = await db.execute(
        select(Node.id, Node.parent_id, Node.title).where(Node.project_id == project_id)
    )
    by_id = {nid: (parent, title) for nid, parent, title in rows.all()}
    out: dict[uuid.UUID, list[str]] = {}
    for nid in node_ids:
        path: list[str] = []
        cur: uuid.UUID | None = nid
        while cur is not None and cur in by_id:
            parent, title = by_id[cur]
            path.append(title)
            cur = parent
        out[nid] = path[::-1]
    return out


async def list_questions(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: CustomerQuestionStatus | None,
    discipline_id: uuid.UUID | None,
    limit: int,
    after: int | None,
) -> tuple[list[dict[str, Any]], int | None]:
    query = select(Thread).where(Thread.project_id == project_id, Thread.is_customer)
    if status is not None:
        query = query.where(Thread.customer_status == status)
    if discipline_id is not None:
        query = query.where(
            Thread.node_id.in_(select(Node.id).where(Node.discipline_id == discipline_id))
        )
    if after is not None:
        query = query.where(Thread.customer_question_no > after)
    rows = (await db.scalars(query.order_by(Thread.customer_question_no).limit(limit + 1))).all()
    page = list(rows[:limit])
    threads = await feed.threads_out(db, page)
    answers = (
        await db.scalars(
            select(Message)
            .where(
                Message.thread_id.in_([t.id for t in page]),
                Message.kind == MessageKind.CUSTOMER_ANSWER,
            )
            .distinct(Message.thread_id)
            .order_by(Message.thread_id, Message.created_at.desc(), Message.id.desc())
        )
    ).all()
    answer_out = dict(
        zip((m.thread_id for m in answers), await feed.messages_out(db, answers), strict=True)
    )
    paths = await node_paths(db, project_id, {t.node_id for t in page if t.node_id})
    items = [
        {
            "thread": out,
            "path": paths.get(t.node_id, []) if t.node_id else [],
            "answer": answer_out.get(t.id),
        }
        for t, out in zip(page, threads, strict=True)
    ]
    last = page[-1].customer_question_no if len(rows) > limit and page else None
    return items, last
