"""Ленты обсуждений и список вопросов (CORE-040; FR-DISC-01, FR-DISC-04, FR-DISC-09).

Лента узла — все записи с ``node_id`` узла (сообщения, ответы в вопросах, серые события),
лента проекта — записи с ``node_id IS NULL``. Порядок — от новых к старым, курсор по
``(created_at, id)``: первая страница с ``limit=3`` даёт «последние 3 записи», счётчик
``messages_count`` узла — N в «Показать всё (N)». К ленте прилагаются вопросы узла (проекта) —
открытые и решённые, с первым сообщением и числом ответов.

Формы — ``Message``/``Thread`` из contracts/openapi.yaml и ws-events.schema.json: отозванное
сообщение в API отдаётся с ``body = ""`` и ``revoked = true``, в событии — без ключа ``body``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ThreadStatus, UserStatus
from estimator.db.models.discussions import Message, MessageAddressee, Thread
from estimator.db.models.tree import Node
from estimator.db.models.users import User
from estimator.services.common import user_ref
from estimator.services.discussions.addressees import Token, matches


def ts(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


@dataclass(frozen=True)
class Feed:
    """Страница ленты: записи, вопросы, курсорная позиция последней записи."""

    items: list[dict[str, Any]]
    threads: list[dict[str, Any]]
    more: bool
    last: dict[str, str] | None


async def _users(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, dict]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.full_name, User.status).where(User.id.in_(wanted)))
    return {
        uid: user_ref(uid, name, is_active=st is UserStatus.ACTIVE) for uid, name, st in rows.all()
    }


async def _addressees(
    db: AsyncSession, message_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, str | None]]]:
    ids = list(message_ids)
    out: dict[uuid.UUID, list[dict[str, str | None]]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = await db.execute(
        select(
            MessageAddressee.message_id, MessageAddressee.target_type, MessageAddressee.target_id
        )
        .where(MessageAddressee.message_id.in_(ids))
        .order_by(MessageAddressee.target_type, MessageAddressee.target_id)
    )
    for mid, kind, target in rows.all():
        out[mid].append({"target_type": str(kind), "target_id": str(target) if target else None})
    return out


def _message(
    m: Message, users: dict[uuid.UUID, dict], addressees: list[dict[str, str | None]]
) -> dict[str, Any]:
    revoked = m.revoked_at is not None
    return {
        "id": str(m.id),
        "thread_id": str(m.thread_id) if m.thread_id else None,
        "node_id": str(m.node_id) if m.node_id else None,
        "author": users.get(m.author_id) if m.author_id else None,
        "kind": str(m.kind),
        "body": "" if revoked else m.body,
        "event": m.event,
        "needs_answer": m.needs_answer,
        "addressees": addressees,
        "created_at": ts(m.created_at),
        "edited_at": ts(m.edited_at),
        "revoked": revoked,
    }


async def messages_out(db: AsyncSession, rows: Sequence[Message]) -> list[dict[str, Any]]:
    users = await _users(db, (m.author_id for m in rows))
    addressees = await _addressees(db, (m.id for m in rows))
    return [_message(m, users, addressees[m.id]) for m in rows]


async def threads_out(db: AsyncSession, rows: Sequence[Thread]) -> list[dict[str, Any]]:
    """``Thread`` API: первое сообщение вопроса и число ответов."""
    if not rows:
        return []
    ids = [t.id for t in rows]
    firsts = (
        await db.scalars(
            select(Message)
            .where(Message.thread_id.in_(ids))
            .distinct(Message.thread_id)
            .order_by(Message.thread_id, Message.created_at, Message.id)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Message.thread_id, func.count())
                .where(Message.thread_id.in_(ids))
                .group_by(Message.thread_id)
            )
        ).all()
    )
    first_by = {m.thread_id: m for m in firsts}
    users = await _users(
        db,
        [t.opened_by for t in rows] + [t.resolved_by for t in rows] + [m.author_id for m in firsts],
    )
    addressees = await _addressees(db, (m.id for m in firsts))
    out = []
    for t in rows:
        first = first_by[t.id]
        out.append(
            {
                "id": str(t.id),
                "node_id": str(t.node_id) if t.node_id else None,
                "opened_by": users[t.opened_by],
                "status": str(t.status),
                "resolved_by": users.get(t.resolved_by) if t.resolved_by else None,
                "resolved_at": ts(t.resolved_at),
                "is_customer": t.is_customer,
                "customer_question_no": t.customer_question_no,
                "customer_status": str(t.customer_status) if t.customer_status else None,
                "sent_at": ts(t.sent_at),
                "answered_at": ts(t.answered_at),
                "closed_at": ts(t.closed_at),
                "withdraw_reason": t.withdraw_reason,
                "edited_after_sent": t.edited_after_sent,
                "first_message": _message(first, users, addressees[first.id]),
                "replies_count": int(counts.get(t.id, 1)) - 1,
            }
        )
    return out


def ws_message(message: dict[str, Any], revoked_at: dt.datetime | None = None) -> dict[str, Any]:
    """``Message`` события ws-events.schema.json из формы API."""
    out = {
        k: message[k]
        for k in (
            "id", "node_id", "thread_id", "author", "kind", "needs_answer", "addressees",
            "created_at", "edited_at",
        )
    }  # fmt: skip
    out["revoked_at"] = ts(revoked_at)
    if not message["revoked"]:
        out["body"] = message["body"]
    return out


def ws_thread(thread: Thread, addressees: list[dict[str, str | None]]) -> dict[str, Any]:
    """``Thread`` события ws-events.schema.json."""
    return {
        "id": str(thread.id),
        "node_id": str(thread.node_id) if thread.node_id else None,
        "opened_by": str(thread.opened_by),
        "status": str(thread.status),
        "resolved_by": str(thread.resolved_by) if thread.resolved_by else None,
        "resolved_at": ts(thread.resolved_at),
        "is_customer": thread.is_customer,
        "customer_question_no": thread.customer_question_no,
        "customer_status": str(thread.customer_status) if thread.customer_status else None,
        "addressees": addressees,
    }


def _at(node_id: uuid.UUID | None, column: Any) -> Any:
    return column.is_(None) if node_id is None else column == node_id


def _after(query: Select[Any], after: dict[str, str] | None, created: Any, ident: Any) -> Any:
    if after is None:
        return query
    at = dt.datetime.fromisoformat(after["at"])
    pid = uuid.UUID(after["id"])
    return query.where(or_(created < at, and_(created == at, ident < pid)))


def position(item: dict[str, Any], created_at: dt.datetime) -> dict[str, str]:
    return {"at": created_at.isoformat(), "id": item["id"]}


async def feed(
    db: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID | None,
    *,
    limit: int,
    after: dict[str, str] | None,
) -> Feed:
    """Лента узла (``node_id``) или проекта (``None``) и вопросы этого уровня."""
    query = select(Message).where(Message.project_id == project_id, _at(node_id, Message.node_id))
    query = _after(query, after, Message.created_at, Message.id)
    rows = (
        await db.scalars(
            query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
        )
    ).all()
    page = list(rows[:limit])
    threads = (
        await db.scalars(
            select(Thread)
            .where(Thread.project_id == project_id, _at(node_id, Thread.node_id))
            .order_by(Thread.created_at.desc(), Thread.id.desc())
        )
    ).all()
    last = position({"id": str(page[-1].id)}, page[-1].created_at) if page else None
    return Feed(
        items=await messages_out(db, page),
        threads=await threads_out(db, threads),
        more=len(rows) > limit,
        last=last,
    )


@dataclass(frozen=True)
class ThreadFilter:
    status: ThreadStatus | None = None
    to_me: frozenset[Token] | None = None
    discipline_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None
    project_level: bool | None = None


def addressed(tokens: Iterable[Token]) -> Any:
    """Вопросы, где среди адресатов первого сообщения есть кто-то из ``tokens``."""
    return Thread.id.in_(
        select(Message.thread_id)
        .join(MessageAddressee, MessageAddressee.message_id == Message.id)
        .where(Message.needs_answer, Message.thread_id.is_not(None), matches(tokens))
    )


async def list_threads(
    db: AsyncSession,
    project_id: uuid.UUID,
    flt: ThreadFilter,
    *,
    limit: int,
    after: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], bool, dict[str, str] | None]:
    query = select(Thread).where(Thread.project_id == project_id)
    if flt.status is not None:
        query = query.where(Thread.status == flt.status)
    if flt.to_me is not None:
        query = query.where(addressed(flt.to_me))
    if flt.discipline_id is not None:
        query = query.where(
            Thread.node_id.in_(select(Node.id).where(Node.discipline_id == flt.discipline_id))
        )
    if flt.node_id is not None:
        query = query.where(Thread.node_id == flt.node_id)
    if flt.project_level is True:
        query = query.where(Thread.node_id.is_(None))
    elif flt.project_level is False:
        query = query.where(Thread.node_id.is_not(None))
    query = _after(query, after, Thread.created_at, Thread.id)
    rows = (
        await db.scalars(
            query.order_by(Thread.created_at.desc(), Thread.id.desc()).limit(limit + 1)
        )
    ).all()
    page = list(rows[:limit])
    last = position({"id": str(page[-1].id)}, page[-1].created_at) if page else None
    return await threads_out(db, page), len(rows) > limit, last
