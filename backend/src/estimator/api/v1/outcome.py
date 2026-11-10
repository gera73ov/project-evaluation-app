"""«Результат пресейла» и журнал проекта (CORE-029, CORE-032; contracts/openapi.yaml
``GET/PUT /projects/{id}/outcome``, ``GET /projects/{id}/journal``).

Gate проверяет ``project.read`` / ``outcome.write`` / ``journal.read``. Сумма договора в ответе —
только с ``money.read`` (и TOTP, ``access.money``); передать её в ``PUT`` можно только с
``money.write`` — иначе 403 ``FORBIDDEN`` или ``TOTP_REQUIRED`` (контракт ``ProjectOutcomePut``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request

from estimator.api.common.errors import ApiError
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.api.v1.projects import _load
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep
from estimator.security.authz.deps import target_from_path
from estimator.services.projects import journal
from estimator.services.projects import outcome as service

router = ApiRouter(tags=["Проекты"])


def _with_money(request: Request) -> bool:
    access = getattr(request.state, "access", None)
    return bool(access and access.money)


@router.get(
    "/projects/{id}/outcome",
    permission="project.read",
    response_model=s.ProjectOutcomeOut,
    response_model_exclude_unset=True,
)
async def get_outcome(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    return await service.outcome_view(db, project, with_money=_with_money(request))


@router.put(
    "/projects/{id}/outcome",
    permission="outcome.write",
    response_model=s.ProjectOutcomeOut,
    response_model_exclude_unset=True,
)
async def put_outcome(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ProjectOutcomePut,
    request: Request,
    principal: ActivePrincipal,
    authz: AuthorizerDep,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    change = service.OutcomeChange(
        outcome=body.outcome,
        loss_reason_id=body.loss_reason_id,
        loss_reason_text=body.loss_reason_text,
    )
    if "contract_amount" in body.model_fields_set:
        await authz.check("money.write", await target_from_path(request, db))
        change = service.OutcomeChange(
            outcome=body.outcome,
            loss_reason_id=body.loss_reason_id,
            loss_reason_text=body.loss_reason_text,
            contract_amount=body.contract_amount,
        )
    await service.update_outcome(db, principal, project, change)
    return await service.outcome_view(db, project, with_money=_with_money(request))


JOURNAL_SCOPE = "project-journal"


@router.get(
    "/projects/{id}/journal",
    permission="journal.read",
    response_model=s.JournalPage,
    response_model_exclude_unset=True,
)
async def get_journal(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    page: PageParams,
    db: DbSession,
) -> dict[str, Any]:
    """Журнал проекта, новые сверху (11.6 №1); денежные записи — только с ``money.read``."""
    after = page.position(JOURNAL_SCOPE)
    last: uuid.UUID | None = None
    if after is not None:
        try:
            last = uuid.UUID(str(after["id"]))
        except (KeyError, ValueError):
            raise ApiError("CURSOR_INVALID") from None
    await _load(db, id)
    items, position = await journal.page(
        db, id, money=_with_money(request), after=last, limit=page.limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(JOURNAL_SCOPE, {"id": str(position)}) if position else None,
    }
