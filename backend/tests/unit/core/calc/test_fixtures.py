"""CORE-007 · расчёт на эталонных фикстурах CORE-001 (TC-CALC-01, TC-CALC-03, TC-CALC-04,
TC-MONEY-01): сервер обязан выдать ровно ожидаемые значения после ROUND_HALF_UP."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from estimator.domain.calc import round_half_up

from ._shape import EDGE, PORTAL, assert_matches, shape

EXPECTED = PORTAL["expected"]


@pytest.fixture(scope="module")
def portal() -> dict[str, Any]:
    return shape(PORTAL["input"], EXPECTED)


@pytest.mark.tc("TC-CALC-01")
@pytest.mark.spec("6.5")
@pytest.mark.parametrize(
    "group", ["leaves", "nodes", "disciplines", "phases", "works", "pm", "total"]
)
def test_portal_hours(portal: dict[str, Any], group: str) -> None:
    assert_matches(portal[group], EXPECTED[group], group)


@pytest.mark.tc("TC-CALC-01")
@pytest.mark.tc("TC-MONEY-01")
@pytest.mark.spec("BR-MONEY-04")
@pytest.mark.parametrize("figure", ["e", "p80", "p90"])
def test_portal_money(portal: dict[str, Any], figure: str) -> None:
    money = EXPECTED["money"]
    assert portal["money"]["quote_figure"] == money["quote_figure"]
    assert_matches(portal["money"]["by_figure"][figure], money["by_figure"][figure], figure)


@pytest.mark.spec("BR-MONEY-04")
def test_portal_currency_total_is_sum_of_rows_not_rounded_total(portal: dict[str, Any]) -> None:
    total_cur = portal["money"]["by_figure"]["e"]["total_cur"]
    assert str(total_cur) != EXPECTED["money"]["naive_total_cur_wrong"]
    assert str(total_cur) == "12397"


@pytest.mark.spec("6.5")
def test_portal_pm_sigma_is_exactly_3_45(portal: dict[str, Any]) -> None:
    """σ УП = 0,18 · 115/6 = 3,45 ровно: плавающая точка дала бы 3,4499… → 3,4."""
    sigma = portal["pm"]["values"]["sigma_exact"]
    assert abs(sigma - Decimal("3.45")) < Decimal("1e-30")
    assert round_half_up(sigma, 1) == Decimal("3.5")
    assert round_half_up(Decimal("3.4499999999999999999999999999999999999"), 1) == Decimal("3.5")


@pytest.mark.spec("6.6")
@pytest.mark.spec("BR-TREE-09")
def test_portal_analytics(portal: dict[str, Any]) -> None:
    assert_matches(portal["analytics"], EXPECTED["analytics"], "analytics")


def _cases() -> list[Any]:
    marks = {
        "invalid-and-empty-leaves": [pytest.mark.tc("TC-CALC-03")],
        "project-e-zero": [pytest.mark.tc("TC-CALC-04")],
        "pm-base-subset": [pytest.mark.tc("TC-CALC-04")],
        "multiplier-sigma-linear": [pytest.mark.tc("TC-CALC-02")],
        "collapse-suggestion": [pytest.mark.tc("TC-TREE-01")],
        "split-keeps-e": [pytest.mark.tc("TC-TREE-01")],
    }
    return [
        pytest.param(case, id=case["id"], marks=marks.get(case["id"], [])) for case in EDGE["cases"]
    ]


@pytest.mark.spec("BR-CALC-03")
@pytest.mark.parametrize("case", _cases())
def test_edge_case(case: dict[str, Any]) -> None:
    expected = dict(case["expected"])
    not_expected = expected.pop("not_expected", None)
    actual = shape(case["input"], expected)
    assert_matches(actual, expected, case["id"])
    if not_expected is not None:
        for node_id, fields in not_expected["nodes"].items():
            for field, wrong in fields.items():
                got = round_half_up(actual["nodes"][node_id][field], 1)
                assert str(got) != wrong, f"{node_id}.{field} = {wrong} — запрещённое значение"
