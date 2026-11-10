"""CORE-050 · деньги статистики (SPEC 10.1 «Итоги», «Сумма для КП», 11.9; BR-MONEY-01…06, G-11).

Стоимость по дисциплинам (строка УП — ``discipline_id: null``) и по фазам — по E без НДС;
цифры для КП — как в ``GET /projects/{id}/money``; динамика «в КП» в валюте — из
``project_totals_daily``. Вызывающий проверил ``money.read``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.models.projects import Project
from estimator.domain import calc
from estimator.services.money.project import _figure, _row_id, money_settings
from estimator.services.money.totals import DailyTotals


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


async def stats_money(
    db: AsyncSession, project: Project, result: calc.ProjectResult, daily: list[DailyTotals]
) -> dict[str, Any]:
    settings = await money_settings(db, project.id)
    money = None if settings is None else calc.calculate_money(result, settings)
    by_figure = {} if money is None or money.by_figure is None else money.by_figure
    by_e = by_figure.get(calc.QuoteFigure.E)
    by_discipline = [
        {"discipline_id": _row_id(row), "cost_rub": _money(value)}
        for row, value in (by_e.rows_rub.items() if by_e else ())
    ]
    rates = {} if settings is None else dict(settings.rates)
    by_phase: list[dict[str, Any]] = []
    for phase_id, cells in result.discipline_by_phase.items():
        total: Decimal | None = Decimal(0)
        for discipline_id, figures in cells.items():
            rate = rates.get(discipline_id)
            if figures.e and rate is None:
                total = None
                break
            total += calc.round_half_up(figures.e * (rate or 0), 0)  # type: ignore[operator]
        by_phase.append({"phase_id": phase_id, "cost_rub": _money(total)})
    return {
        "cost_by_discipline": by_discipline,
        "cost_by_phase": by_phase,
        "figures": {f.value: _figure(m) for f, m in by_figure.items()},
        "dynamics": [{"date": d.date.isoformat(), "quote_cur": _money(d.quote_cur)} for d in daily],
    }
