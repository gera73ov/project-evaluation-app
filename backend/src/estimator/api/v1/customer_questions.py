"""Вопросы заказчику (CORE-044; contracts/openapi.yaml ``listCustomerQuestions``,
``answerCustomerQuestion``, ``withdrawCustomerQuestion``, ``editCustomerQuestion``).

Права ``cq.*`` и условие «только в статусе new» для автора-эксперта проверяет gate по объекту
``/threads/{id}`` (резолвер в :mod:`estimator.api.v1.discussions`); закрытие и переоткрытие —
``POST /threads/{id}/resolve`` и ``/reopen``. Выгрузка (``…/customer-questions/export``) — EXP-007,
она переводит выгруженные «новые» в «отправлен» через ``flow.mark_sent``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.api.v1.discussions import _limit, _thread_out
from estimator.auth.mfa_policy import ActivePrincipal, RedisDep
from estimator.db.enums import CustomerQuestionStatus
from estimator.db.models.discussions import Thread
from estimator.db.session import DbSession
from estimator.services.customer_questions import flow, listing

router = ApiRouter(tags=["Обсуждения"])


async def _thread(db: AsyncSession, thread_id: uuid.UUID) -> Thread:
    thread = await db.get(Thread, thread_id)
    if thread is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return thread


@router.get(
    "/projects/{id}/customer-questions",
    permission="cq.read",
    response_model=s.CustomerQuestionList,
    response_model_exclude_unset=True,
)
async def list_customer_questions(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    db: DbSession,
    status: Annotated[CustomerQuestionStatus | None, Query()] = None,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    scope = f"cq:{id}"
    after = page.position(scope)
    items, last = await listing.list_questions(
        db,
        id,
        status=status,
        discipline_id=discipline_id,
        limit=page.limit,
        after=int(after["no"]) if after else None,
    )
    return {"items": items, "next_cursor": encode_cursor(scope, {"no": last}) if last else None}


@router.post(
    "/threads/{id}/answer",
    permission="cq.answer",
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def answer_customer_question(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CqAnswer,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    await _limit(redis, principal)
    thread = await _thread(db, id)
    await flow.answer(db, principal, thread, body.body)
    return await _thread_out(db, thread)


@router.post(
    "/threads/{id}/withdraw",
    permission="cq.withdraw",
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def withdraw_customer_question(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CqWithdraw,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    thread = await _thread(db, id)
    await flow.withdraw(db, principal, thread, body.reason)
    return await _thread_out(db, thread)


@router.patch(
    "/threads/{id}/question",
    permission="cq.edit",
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def edit_customer_question(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CqEdit,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    thread = await _thread(db, id)
    await flow.edit(db, principal, thread, body.body)
    return await _thread_out(db, thread)
