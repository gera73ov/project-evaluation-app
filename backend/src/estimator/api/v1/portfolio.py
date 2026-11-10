"""Портфель руководителя пресейла (CORE-070; contracts/openapi.yaml ``GET /portfolio/projects``,
``GET /portfolio/summary``).

Право — ``portfolio.read`` (руководитель пресейла, TOTP — gate); расчёты —
:mod:`estimator.services.portfolio`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from estimator.api.common.errors import ApiError
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1.core_schemas import UserRef
from estimator.db.enums import ProjectOutcome, ProjectStatus, QuoteFigure
from estimator.db.session import DbSession
from estimator.services import portfolio

router = ApiRouter(tags=["Руководитель пресейла"])
SCOPE = "portfolio"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PortfolioItemMoney(_Strict):
    currency: str
    quote_cur: str | None
    quote_rub: str | None
    cost_rub: str | None
    contract_amount: str | None
    rates_missing: bool


class PortfolioItem(_Strict):
    id: uuid.UUID
    name: str
    customer: str
    moderators: list[UserRef]
    presales: list[UserRef]
    status: ProjectStatus
    outcome: ProjectOutcome
    quote_figure: QuoteFigure
    quote_hours: str | None
    no_moderator: bool
    created_at: dt.datetime
    updated_at: dt.datetime
    money: PortfolioItemMoney


class PortfolioList(_Strict):
    items: list[PortfolioItem]
    next_cursor: str | None


class Period(_Strict):
    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")


class LossReasonCount(_Strict):
    loss_reason_id: uuid.UUID | None
    name: str
    count: int
    texts: list[str]


class MonthOutcomes(_Strict):
    month: str
    won: int
    lost: int
    cancelled: int


class PortfolioSummary(_Strict):
    period: Period
    by_status: dict[str, int]
    by_outcome: dict[str, int]
    won_share_count_pct: str | None
    won_share_money_pct: str | None
    sum_won_cur: str | None
    sum_lost_cur: str | None
    sum_in_progress_cur: str | None
    loss_reasons: list[LossReasonCount]
    contract_to_quote_median_pct: str | None
    by_month: list[MonthOutcomes]
    first_snapshot_median_days: str | None


@router.get(
    "/portfolio/projects",
    permission="portfolio.read",
    response_model=PortfolioList,
    response_model_exclude_unset=True,
)
async def list_portfolio(
    db: DbSession,
    page: PageParams,
    status: ProjectStatus | None = None,
    outcome: ProjectOutcome | None = None,
    moderator_id: uuid.UUID | None = None,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """Реестр всех проектов с деньгами (FR-PORT-01, 11.13 №6)."""
    after = page.position(SCOPE)
    key = None if after is None else after.get("k")
    if after is not None and not (
        isinstance(key, list) and len(key) == 2 and all(isinstance(k, str) for k in key)
    ):
        raise ApiError("CURSOR_INVALID")
    try:
        items, last = await portfolio.projects(
            db,
            portfolio.PortfolioFilter(status, outcome, moderator_id, date_from, date_to, q),
            after=key,
            limit=page.limit,
        )
    except ValueError as exc:  # подписанный, но не наш формат позиции
        raise ApiError("CURSOR_INVALID") from exc
    return {"items": items, "next_cursor": encode_cursor(SCOPE, {"k": last}) if last else None}


@router.get(
    "/portfolio/summary",
    permission="portfolio.read",
    response_model=PortfolioSummary,
    response_model_exclude_unset=True,
)
async def portfolio_summary(
    db: DbSession,
    date_from: Annotated[dt.date, Query(alias="from")],
    date_to: Annotated[dt.date, Query(alias="to")],
) -> dict[str, Any]:
    """Сводка по портфелю за период (FR-PORT-02, GAP-05, 11.13 №2–5)."""
    return await portfolio.summary(db, date_from, date_to)
