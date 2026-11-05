"""CORE-005 · деньги: ставки, НДС, валюта, переполнение (SPEC 6.4, BR-MONEY-02…05)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from estimator.domain.calc import (
    PM_ROW,
    MoneySettings,
    QuoteFigure,
    calculate,
    calculate_money,
    project_cache,
)

from ._build import branch, leaf, project, rub

D = Decimal
BIG = "99999.5-99999.5-99999.5"


def _money(nodes, settings: MoneySettings, pm: str = "18", quote=QuoteFigure.P80):
    result = calculate(project(nodes, pm=pm, money=settings, quote=quote))
    return result, calculate_money(result, settings)


@pytest.mark.tc("TC-MONEY-01")
@pytest.mark.spec("BR-MONEY-06")
def test_quote_block_and_labels() -> None:
    nodes = [*branch("a", "be"), leaf("l1", "a-be", "a", "be", "8-12-20")]
    _, money = _money(nodes, rub({"be": "3000", None: "3200"}, vat="22"))
    assert money.vat_label == "НДС 22%"
    assert money.quote is not None
    assert money.quote.figure is QuoteFigure.P80
    assert money.quote.rows_rub["qa"] == 0  # дисциплина без часов и без ставки
    _, no_vat = _money(nodes, rub({"be": "3000", None: "3200"}, vat=None))
    assert no_vat.vat_label == "НДС не облагается"


@pytest.mark.spec("BR-MONEY-02")
def test_rates_missing_hides_sums() -> None:
    nodes = [*branch("a", "be"), leaf("l1", "a-be", "a", "be", "8-12-20")]
    result, money = _money(nodes, rub({}))
    assert money.rates_missing == ["be", PM_ROW]
    assert money.rates_missing_text == "не заданы ставки: Бэкенд, УП"
    assert money.by_figure is None
    assert money.quote is None
    cache = project_cache(result, money)
    assert cache.cost_rub is None
    assert cache.quote_cur is None
    assert cache.e == D("14.95")


@pytest.mark.spec("BR-MONEY-02")
def test_pm_rate_not_needed_when_pm_disabled() -> None:
    nodes = [*branch("a", "be"), leaf("l1", "a-be", "a", "be", "8-12-20")]
    _, money = _money(nodes, rub({"be": "3000"}), pm="0")
    assert money.rates_missing == []
    assert money.by_figure is not None
    assert money.by_figure[QuoteFigure.E].rows_rub[PM_ROW] == 0


@pytest.mark.spec("BR-MONEY-04")
def test_overflow_in_rubles_propagates_to_totals_and_vat() -> None:
    nodes = [*branch("a", "be")] + [
        leaf(f"l{i}", "a-be", "a", "be", BIG, n=10_000) for i in range(10)
    ]
    settings = rub({"be": "999999999999", None: "1"}, vat="20")
    result, money = _money(nodes, settings, pm="0")
    assert money.by_figure is not None
    block = money.by_figure[QuoteFigure.E]
    assert block.rows_rub["be"] is None
    assert block.overflow_rub
    assert block.overflow_cur
    assert block.total_rub is block.vat_rub is block.total_with_vat_rub is None
    assert block.total_cur is block.vat_cur is block.total_with_vat_cur is None
    assert project_cache(result, money).cost_rub is None


@pytest.mark.spec("BR-MONEY-04")
def test_overflow_only_in_vat() -> None:
    """Итог без НДС ещё помещается, а НДС и «с НДС» — нет."""
    nodes = [*branch("a", "be")] + [
        leaf(f"l{i}", "a-be", "a", "be", BIG, n=10_000) for i in range(10)
    ]
    # E = 9 999 950 000 ч; ставка подобрана так, что итог чуть меньше 10^20
    settings = MoneySettings("RUB", D(1), D("50"), {"be": D("9000000000"), None: D(1)})
    _, money = _money(nodes, settings, pm="0")
    assert money.by_figure is not None
    block = money.by_figure[QuoteFigure.E]
    assert block.total_rub is not None
    assert block.vat_rub is not None
    assert block.total_with_vat_rub is None
    assert block.total_with_vat_cur is None


@pytest.mark.spec("BR-MONEY-04")
def test_overflow_only_in_vat_currency() -> None:
    nodes = [*branch("a", "be")] + [
        leaf(f"l{i}", "a-be", "a", "be", BIG, n=10_000) for i in range(10)
    ]
    settings = MoneySettings("USD", D("0.5"), D("50"), {"be": D("4000000000"), None: D(1)})
    _, money = _money(nodes, settings, pm="0")
    assert money.by_figure is not None
    block = money.by_figure[QuoteFigure.E]
    assert block.total_cur is not None
    assert block.vat_cur is not None
    assert block.total_with_vat_cur is None


def test_project_cache_without_money_and_hours_overflow() -> None:
    nodes = [*branch("a", "be"), leaf("l1", "a-be", "a", "be", "1-1-1")]
    result = calculate(project(nodes))
    assert project_cache(result, None).e == D("1.00")
    huge = [*branch("a", "be")] + [
        leaf(f"l{i}", "a-be", "a", "be", BIG, n=10_000) for i in range(1001)
    ]
    assert project_cache(calculate(project(huge)), None).e is None


def test_overflow_of_vat_itself() -> None:
    """НДС больше итога (ставка NUMERIC(5,2) допускает > 100%) и не помещается сам."""
    nodes = [*branch("a", "be")] + [
        leaf(f"l{i}", "a-be", "a", "be", BIG, n=10_000) for i in range(10)
    ]
    settings = MoneySettings("RUB", D(1), D("200"), {"be": D("6000000000"), None: D(1)})
    _, money = _money(nodes, settings, pm="0")
    assert money.by_figure is not None
    block = money.by_figure[QuoteFigure.E]
    assert block.total_rub is not None
    assert block.vat_rub is None
    assert block.vat_cur is None
    assert block.total_with_vat_rub is None
