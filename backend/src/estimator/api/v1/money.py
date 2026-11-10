"""Деньги проекта (CORE-030; contracts/openapi.yaml ``GET/PUT /projects/{id}/money``).

Gate проверяет ``money.read`` / ``money.write`` и пройденный в сессии TOTP (``totp_gate``):
эксперт получает 403 ``FORBIDDEN``, модератор без TOTP — 403 ``TOTP_REQUIRED``, руководитель
пресейла видит деньги любого проекта (контекст ``any_project``).
"""

from __future__ import annotations

import uuid
from typing import Any

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.api.v1.projects import _load
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.services.money import project as money

router = ApiRouter(tags=["Проекты"])


@router.get(
    "/projects/{id}/money",
    permission="money.read",
    response_model=s.ProjectMoneyOut,
    response_model_exclude_unset=True,
)
async def get_money(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    return await money.money_view(db, await _load(db, id))


@router.put(
    "/projects/{id}/money",
    permission="money.write",
    response_model=s.ProjectMoneyOut,
    response_model_exclude_unset=True,
)
async def put_money(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ProjectMoneyPut,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    change = money.MoneyChange(
        currency=body.currency,
        exchange_rate=body.exchange_rate,
        vat_rate_id=body.vat_rate_id,
        rates=None if body.rates is None else [(r.discipline_id, r.rate_rub) for r in body.rates],
    )
    return await money.update_money(db, principal, project, change)
