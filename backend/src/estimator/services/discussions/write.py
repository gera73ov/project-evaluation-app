"""Запись в обсуждения: сообщение, вопрос, ответ в вопросе (CORE-040; FR-DISC-02, 03, 09).

* Текст 1–4 000 символов хранится как есть (без HTML/Markdown, SEC-WEB-02); только пробелы —
  ``VALIDATION_FAILED``.
* Флаг «нужен ответ» открывает вопрос (``threads``); без адресатов вопрос получает адресата по
  умолчанию (:func:`~estimator.services.discussions.addressees.default_for`).
* Адресат ``@заказчик`` ставит флаг сам и делает вопрос заказчику: ``is_customer``, статус
  ``new``, номер В-NNN из ``projects.next_question_no`` (атомарно, номера не переиспользуются;
  переходы статусов — CORE-044).
* Ответ в вопросе ссылается на вопрос, флага «нужен ответ» не несёт и уведомляет автора вопроса
  («ответ на мой вопрос»); адресаты ответа — упоминания, нового вопроса они не открывают.

События: ``thread.created`` и ``message.created`` — каждое со своей версией проекта (ARCH-02).
Право ``discussion.write`` по статусу проекта (в «Подготовке» — модераторы, в «Завершена» и
«Архиве» — только чтение, M3.4-05) проверяет gate маршрута.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.enums import AddresseeType, CustomerQuestionStatus, MessageKind, ThreadStatus
from estimator.db.models.discussions import Message, MessageAddressee, Thread
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.notifications.inapp import notify
from estimator.services.common import emit
from estimator.services.discussions import addressees as addr
from estimator.services.discussions import feed

RawAddressee = tuple[str, uuid.UUID | None]

_NEXT_NO = text(
    "UPDATE projects SET next_question_no = next_question_no + 1 WHERE id = :id "
    "RETURNING next_question_no - 1"
)


def _body(body: str) -> str:
    if not body.strip():
        raise addr.invalid("body", "сообщение не может быть пустым")
    return body


def _payload(thread: Thread, actor: uuid.UUID) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(thread.project_id),
        "thread_id": str(thread.id),
        "actor_id": str(actor),
        "is_customer": thread.is_customer,
    }
    if thread.node_id is not None:
        payload["node_id"] = str(thread.node_id)
    return payload


async def _store(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    node_id: uuid.UUID | None,
    thread: Thread | None,
    body: str,
    tokens: Sequence[addr.Token],
    *,
    needs_answer: bool,
) -> tuple[Message, dict[str, Any]]:
    message = Message(
        project_id=project.id,
        node_id=node_id,
        thread_id=thread.id if thread else None,
        author_id=principal.user_id,
        body=body,
        kind=MessageKind.MESSAGE,
        needs_answer=needs_answer,
        created_at=dt.datetime.now(dt.UTC),
    )
    db.add(message)
    await db.flush()
    db.add_all(
        MessageAddressee(message_id=message.id, target_type=kind, target_id=target)
        for kind, target in tokens
    )
    await db.flush()
    [out] = await feed.messages_out(db, [message])
    return message, out


async def post(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    node: Node | None,
    body: str,
    raw: Sequence[RawAddressee],
    *,
    needs_answer: bool,
) -> tuple[dict[str, Any], Thread | None]:
    """Сообщение в ленту узла (``node``) или проекта (``None``); с флагом — новый вопрос."""
    body = _body(body)
    squad = await addr.team(db, project.id)
    tokens = addr.validate(raw, squad)
    is_customer = any(kind is AddresseeType.CUSTOMER for kind, _ in tokens)
    needs_answer = needs_answer or is_customer
    if needs_answer and not tokens:
        tokens = addr.default_for(node)
    node_id = node.id if node else None
    thread: Thread | None = None
    if needs_answer:
        number = None
        if is_customer:
            number = int((await db.execute(_NEXT_NO, {"id": project.id})).scalar_one())
        thread = Thread(
            project_id=project.id,
            node_id=node_id,
            opened_by=principal.user_id,
            status=ThreadStatus.OPEN,
            is_customer=is_customer,
            customer_question_no=number,
            customer_status=CustomerQuestionStatus.NEW if is_customer else None,
            created_by=principal.user_id,
            created_at=dt.datetime.now(dt.UTC),
        )
        db.add(thread)
        await db.flush()
    _, out = await _store(
        db, principal, project, node_id, thread, body, tokens, needs_answer=needs_answer
    )
    if thread is not None:
        await emit(
            db,
            project.id,
            "thread.created",
            {"thread": feed.ws_thread(thread, out["addressees"]), "author": out["author"]},
        )
    await emit(db, project.id, "message.created", {"message": feed.ws_message(out)})
    if thread is not None:
        await notify(
            db,
            "question_to_me",
            squad.expand(tokens),
            project_id=project.id,
            node_id=node_id,
            payload=_payload(thread, principal.user_id),
            actor_id=principal.user_id,
        )
    return out, thread


async def reply(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    thread: Thread,
    body: str,
    raw: Sequence[RawAddressee],
) -> dict[str, Any]:
    """Ответ в вопросе: ссылка на вопрос, уведомление «ответ на мой вопрос» его автору."""
    body = _body(body)
    squad = await addr.team(db, project.id)
    tokens = addr.validate(raw, squad)
    _, out = await _store(
        db, principal, project, thread.node_id, thread, body, tokens, needs_answer=False
    )
    await emit(db, project.id, "message.created", {"message": feed.ws_message(out)})
    await notify(
        db,
        "answer_to_my_question",
        [thread.opened_by],
        project_id=project.id,
        node_id=thread.node_id,
        payload=_payload(thread, principal.user_id),
        actor_id=principal.user_id,
    )
    return out
