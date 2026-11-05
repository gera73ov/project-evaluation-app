"""CORE-005 · деньги: строки, НДС, валюта (SPEC 6.4, BR-MONEY-01…06, R-01, Q-40, Q-41, C-31).

Для цифры F (E, P80, P90) коэффициент ``K_F = F_итог / E_итог``; строка дисциплины или УП
``округл(E_строки · ставка · K_F)``; итог — сумма округлённых строк; НДС от итога; валюта —
построчно из рублёвых строк. Значение, не помещающееся в ``NUMERIC(20,0)``, — ``None`` («—»).

Модуль только считает. Кому показывать деньги (BR-MONEY-01), решает сервис денег (CORE-015).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from estimator.domain.calc._decimal import HUNDRED, ZERO, in_calc_context, round_half_up
from estimator.domain.calc.model import PM_ROW, MoneySettings, QuoteFigure
from estimator.domain.calc.project import ProjectResult

MONEY_LIMIT = Decimal(10) ** 20  # NUMERIC(20,0)
HOURS_CACHE_LIMIT = Decimal(10) ** 12  # NUMERIC(14,2)
PM_LABEL = "УП"
NO_VAT_LABEL = "НДС не облагается"


@dataclass(frozen=True, slots=True)
class FigureMoney:
    """Деньги одной цифры. ``None`` в сумме — переполнение ``NUMERIC(20,0)``."""

    figure: QuoteFigure
    k: Decimal | None  # K_F; при E = 0 не вычисляется
    rows_rub: dict[str, Decimal | None]  # id дисциплины или "pm" → сумма
    total_rub: Decimal | None
    vat_rub: Decimal | None  # None и при «без НДС», и при переполнении
    total_with_vat_rub: Decimal | None
    rows_cur: dict[str, Decimal | None]
    total_cur: Decimal | None
    vat_cur: Decimal | None
    total_with_vat_cur: Decimal | None
    overflow_rub: bool
    overflow_cur: bool


@dataclass(frozen=True, slots=True)
class MoneyResult:
    currency: str
    vat_percent: Decimal | None
    quote_figure: QuoteFigure
    rates_missing: list[str]  # id дисциплин и "pm" (BR-MONEY-02)
    rates_missing_text: str | None  # «не заданы ставки: QA, УП»
    by_figure: dict[QuoteFigure, FigureMoney] | None  # None, если ставки не заданы

    @property
    def vat_label(self) -> str:
        return NO_VAT_LABEL if self.vat_percent is None else f"НДС {self.vat_percent:f}%"

    @property
    def quote(self) -> FigureMoney | None:
        return None if self.by_figure is None else self.by_figure[self.quote_figure]


def fits_money(value: Decimal) -> bool:
    return abs(value) < MONEY_LIMIT


def fits_hours_cache(value: Decimal) -> bool:
    return abs(round_half_up(value, 2)) < HOURS_CACHE_LIMIT


def _fit(value: Decimal) -> Decimal | None:
    return value if fits_money(value) else None


def _figure_total(project: ProjectResult, figure: QuoteFigure) -> Decimal:
    total = project.total
    return {QuoteFigure.E: total.e, QuoteFigure.P80: total.p80, QuoteFigure.P90: total.p90}[figure]


def _row_hours(project: ProjectResult) -> dict[str, Decimal]:
    rows = {d.id: project.disciplines[d.id].e for d in project.input.disciplines}
    rows[PM_ROW] = project.pm.e
    return rows


def _rate(money: MoneySettings, row: str) -> Decimal | None:
    return money.rates.get(None if row == PM_ROW else row)


def _sum(values: list[Decimal | None]) -> Decimal | None:
    if any(v is None for v in values):
        return None
    return _fit(sum((v for v in values if v is not None), ZERO))


@in_calc_context
def _figure_money(project: ProjectResult, money: MoneySettings, figure: QuoteFigure) -> FigureMoney:
    e_total = project.total.e
    k = None if e_total == ZERO else _figure_total(project, figure) / e_total
    factor = ZERO if k is None else k  # E = 0: деления нет, все строки равны 0
    rows_rub: dict[str, Decimal | None] = {}
    for row, hours in _row_hours(project).items():
        rate = _rate(money, row) or ZERO  # пустая ставка допустима только при E = 0
        rows_rub[row] = _fit(round_half_up(hours * rate * factor))
    total_rub = _sum(list(rows_rub.values()))
    rate = money.exchange_rate
    rows_cur = {
        row: None if rub is None else _fit(round_half_up(rub / rate))
        for row, rub in rows_rub.items()
    }
    total_cur = _sum(list(rows_cur.values()))
    vat_rub = vat_cur = total_with_vat_rub = total_with_vat_cur = None
    if money.vat_percent is not None and total_rub is not None:
        vat_rub = _fit(round_half_up(total_rub * money.vat_percent / HUNDRED))
        total_with_vat_rub = _sum([total_rub, vat_rub])
        if vat_rub is not None:
            vat_cur = _fit(round_half_up(vat_rub / rate))
        if total_cur is not None:
            total_with_vat_cur = _sum([total_cur, vat_cur])
    return FigureMoney(
        figure=figure,
        k=k,
        rows_rub=rows_rub,
        total_rub=total_rub,
        vat_rub=vat_rub,
        total_with_vat_rub=total_with_vat_rub,
        rows_cur=rows_cur,
        total_cur=total_cur,
        vat_cur=vat_cur,
        total_with_vat_cur=total_with_vat_cur,
        overflow_rub=total_rub is None,
        overflow_cur=total_cur is None,
    )


def rates_missing(project: ProjectResult, money: MoneySettings) -> list[str]:
    """Строки с часами без ставки: дисциплины с E > 0 и УП при E_УП > 0 (BR-MONEY-02)."""
    return [
        row
        for row, hours in _row_hours(project).items()
        if hours > ZERO and _rate(money, row) is None
    ]


def rates_missing_text(project: ProjectResult, missing: list[str]) -> str:
    names = {d.id: d.name for d in project.input.disciplines}
    labels = [PM_LABEL if row == PM_ROW else names[row] for row in missing]
    return "не заданы ставки: " + ", ".join(labels)


def calculate_money(project: ProjectResult, money: MoneySettings) -> MoneyResult:
    """Деньги проекта по E, P80 и P90 (SPEC 6.4)."""
    missing = rates_missing(project, money)
    by_figure = (
        None
        if missing
        else {figure: _figure_money(project, money, figure) for figure in QuoteFigure}
    )
    return MoneyResult(
        currency=money.currency,
        vat_percent=money.vat_percent,
        quote_figure=project.input.quote_figure,
        rates_missing=missing,
        rates_missing_text=rates_missing_text(project, missing) if missing else None,
        by_figure=by_figure,
    )


@dataclass(frozen=True, slots=True)
class ProjectCache:
    """Кэш итогов проекта для списков (14.2). ``None`` — не помещается, в списке «—»."""

    e: Decimal | None  # часы E проекта, NUMERIC(14,2)
    cost_rub: Decimal | None  # стоимость по E без НДС, ₽
    quote_cur: Decimal | None  # «в КП» в валюте без НДС


def project_cache(project: ProjectResult, money: MoneyResult | None) -> ProjectCache:
    e = round_half_up(project.total.e, 2)
    cost = quote = None
    if money is not None and money.by_figure is not None:
        cost = money.by_figure[QuoteFigure.E].total_rub
        quote = money.by_figure[money.quote_figure].total_cur
    return ProjectCache(e if fits_hours_cache(e) else None, cost, quote)
