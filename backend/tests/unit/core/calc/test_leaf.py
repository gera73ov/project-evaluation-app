"""CORE-002 · расчёт листа, нормализация ввода и ×N (SPEC 6.1, BR-CALC-03, BR-CALC-04)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from estimator.domain.calc import (
    CalcInputError,
    LeafState,
    classify,
    estimate,
    fits_hours_cache,
    fits_money,
    normalize_hours,
    round_half_up,
    validate_multiplier,
)

from ._shape import EDGE

D = Decimal
FUNCTIONS = EDGE["functions"]


@pytest.mark.tc("TC-CALC-04")
@pytest.mark.spec("BR-CALC-03")
@pytest.mark.parametrize(
    "item", FUNCTIONS["round_half_up"]["cases"], ids=lambda c: f"{c['value']}@{c['places']}"
)
def test_round_half_up(item: dict) -> None:
    assert str(round_half_up(D(item["value"]), item["places"])) == item["expected"]


@pytest.mark.spec("FR-TREE-21")
@pytest.mark.parametrize(
    "item", FUNCTIONS["normalize_hours"]["cases"], ids=lambda c: repr(c["input"])
)
def test_normalize_hours(item: dict) -> None:
    if "error" in item:
        with pytest.raises(CalcInputError) as err:
            normalize_hours(item["input"])
        assert err.value.code == item["error"]
        return
    result = normalize_hours(item["input"])
    assert result.text == item["expected"]
    assert result.rounded is item["rounded"]


@pytest.mark.spec("BR-CALC-03")
def test_normalize_hours_range_checked_after_rounding() -> None:
    assert normalize_hours("99999.7").text == "99999.5"
    assert normalize_hours(" -0,2 ").text == "0"  # −0,2 → 0 после шага 0,5
    with pytest.raises(CalcInputError):
        normalize_hours("99999.8")


@pytest.mark.spec("NFR-LIM-01")
@pytest.mark.parametrize("item", FUNCTIONS["multiplier"]["cases"], ids=lambda c: repr(c["input"]))
def test_validate_multiplier(item: dict) -> None:
    if "error" in item:
        with pytest.raises(CalcInputError) as err:
            validate_multiplier(item["input"])
        assert err.value.code == item["error"]
    else:
        assert validate_multiplier(item["input"]) == item["input"]


@pytest.mark.parametrize("raw", [True, 2.0, None, "x"])
def test_validate_multiplier_rejects_non_integers(raw: object) -> None:
    with pytest.raises(CalcInputError) as err:
        validate_multiplier(raw)
    assert err.value.code == "VALIDATION_FAILED"


def test_validate_multiplier_accepts_digit_string() -> None:
    assert validate_multiplier(" 12 ") == 12


@pytest.mark.spec("BR-CALC-02")
@pytest.mark.spec("BR-CALC-04")
@pytest.mark.parametrize(
    ("orp", "state"),
    [
        ((None, D(1), D(2)), LeafState.EMPTY),
        ((D(1), None, D(2)), LeafState.EMPTY),
        ((D(1), D(2), None), LeafState.EMPTY),
        ((D(3), D(2), D(4)), LeafState.INVALID),
        ((D(1), D(5), D(4)), LeafState.INVALID),
        ((D(0), D(0), D(0)), LeafState.ZERO),
        ((D(5), D(5), D(5)), LeafState.VALID),
        ((D(0), D(2), D(4)), LeafState.VALID),
    ],
)
def test_classify(orp: tuple, state: LeafState) -> None:
    assert classify(*orp) is state
    assert state.counted is (state in (LeafState.VALID, LeafState.ZERO))


@pytest.mark.spec("6.1")
def test_estimate_pert_and_linear_sigma() -> None:
    leaf = estimate(D(4), D(6), D(8), 12)
    assert leaf.e_unit == D(6)
    assert leaf.e == D(72)
    assert leaf.sigma == D(8)  # N·σ, а не √N·σ
    assert round_half_up(leaf.p80, 2) == D("78.73")
    assert round_half_up(leaf.p90, 2) == D("82.25")


def test_estimate_of_uncounted_leaf_is_zero() -> None:
    leaf = estimate(D(3), D(2), D(4), 5)
    assert (leaf.state, leaf.e, leaf.sigma) == (LeafState.INVALID, 0, 0)


@pytest.mark.spec("14.2")
@pytest.mark.parametrize("item", FUNCTIONS["fits_cache"]["cases"], ids=lambda c: c["value"])
def test_fits_cache(item: dict) -> None:
    check = fits_hours_cache if item["type"] == "hours" else fits_money
    assert check(D(item["value"])) is item["fits"]
