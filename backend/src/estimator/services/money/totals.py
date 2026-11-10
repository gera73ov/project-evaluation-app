"""CORE-026 · строка кэша ``project_totals``: расчёт и запись; чтение для списков (CORE-033).

Часы E, P80, P90 — ``NUMERIC(14,2)``, деньги без НДС — ``NUMERIC(20,0)``: стоимость по E
(``cost_rub``), «в КП» в рублях и в валюте КП (``quote_rub``, ``quote_cur``). Не помещается или не
вычисляется (не заданы ставки) — ``NULL`` (BR-MONEY-04). Денежные поля списку отдаются только
для проектов с ``money.read`` (FR-HOME-04, SEC-AUTHZ-05) — решает вызывающий через ``with_money``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.money import ProjectMoney, ProjectTotals
from estimator.db.models.projects import Project
from estimator.domain import calc
from estimator.domain.calc.money import fits_hours_cache
from estimator.services.money.project import money_settings
from estimator.services.tree.load import compute


def _hours(value: Decimal) -> Decimal | None:
    rounded = calc.round_half_up(value, 2)
    return rounded if fits_hours_cache(rounded) else None


async def refresh(db: AsyncSession, project: Project, now: dt.datetime | None = None) -> None:
    """Пересчитать итоги проекта и записать строку кэша (upsert)."""
    result = (await compute(db, project)).result
    settings = await money_settings(db, project.id)
    money = None if settings is None else calc.calculate_money(result, settings)
    quote = None if money is None else money.quote
    by_e = None if money is None or money.by_figure is None else money.by_figure[calc.QuoteFigure.E]
    values = {
        "e": _hours(result.total.e),
        "p80": _hours(result.total.p80),
        "p90": _hours(result.total.p90),
        "cost_rub": None if by_e is None else by_e.total_rub,
        "quote_rub": None if quote is None else quote.total_rub,
        "quote_cur": None if quote is None else quote.total_cur,
        "rates_missing": bool(money and money.rates_missing),
        "project_version": project.version,
        "updated_at": now or dt.datetime.now(dt.UTC),
    }
    stmt = insert(ProjectTotals).values(project_id=project.id, **values)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=[ProjectTotals.project_id], set_=values)
    )


@dataclass(frozen=True)
class CachedTotals:
    e: Decimal | None
    p80: Decimal | None
    p90: Decimal | None
    updated_at: dt.datetime
    money: ListMoney | None  # None без money.read


@dataclass(frozen=True)
class ListMoney:
    """Деньги строки списка (``ProjectListItemMoney``): «в КП» без НДС."""

    currency: str
    quote_cur: Decimal | None
    quote_rub: Decimal | None
    rates_missing: bool


async def cached(
    db: AsyncSession, project_ids: Collection[uuid.UUID], with_money: Collection[uuid.UUID]
) -> dict[uuid.UUID, CachedTotals]:
    """Кэш итогов проектов; деньги — только для ``with_money``."""
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(ProjectTotals, ProjectMoney.currency)
            .outerjoin(ProjectMoney, ProjectMoney.project_id == ProjectTotals.project_id)
            .where(ProjectTotals.project_id.in_(project_ids))
        )
    ).all()
    return {
        r.project_id: CachedTotals(
            e=r.e,
            p80=r.p80,
            p90=r.p90,
            updated_at=r.updated_at,
            money=ListMoney(currency, r.quote_cur, r.quote_rub, r.rates_missing)
            if r.project_id in with_money and currency is not None
            else None,
        )
        for r, currency in rows
    }


@dataclass(frozen=True)
class PortfolioMoney:
    """Деньги строки портфеля (``PortfolioItemMoney``, CORE-070): «в КП» и стоимость без НДС,
    сумма договора в валюте КП."""

    currency: str
    quote_cur: Decimal | None
    quote_rub: Decimal | None
    cost_rub: Decimal | None
    contract_amount: Decimal | None
    rates_missing: bool


async def portfolio_money(
    db: AsyncSession, project_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, PortfolioMoney]:
    """Деньги проектов для портфеля руководителя пресейла (право ``portfolio.read`` — у
    вызывающего)."""
    if not project_ids:
        return {}
    rows = await db.execute(
        select(ProjectMoney, ProjectTotals)
        .outerjoin(ProjectTotals, ProjectTotals.project_id == ProjectMoney.project_id)
        .where(ProjectMoney.project_id.in_(project_ids))
    )
    out: dict[uuid.UUID, PortfolioMoney] = {}
    for money, totals in rows.all():
        out[money.project_id] = PortfolioMoney(
            currency=money.currency,
            quote_cur=None if totals is None else totals.quote_cur,
            quote_rub=None if totals is None else totals.quote_rub,
            cost_rub=None if totals is None else totals.cost_rub,
            contract_amount=money.contract_amount,
            rates_missing=bool(totals and totals.rates_missing),
        )
    return out
