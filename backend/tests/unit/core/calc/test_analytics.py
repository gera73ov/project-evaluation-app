"""CORE-006 · доли, контрольные соотношения, объёмы, «крупные» листья (SPEC 6.6, BR-TREE-09)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from estimator.domain.calc import DetailLevel, Node, NodeKind, calculate
from estimator.domain.calc.analytics import (
    Verdict,
    control_ratio,
    decomposition,
    large_leaf_threshold,
    shares,
    volumes,
    volumes_text,
)

from ._build import branch, leaf, project

D = Decimal


def _project(level: DetailLevel = DetailLevel.MEDIUM):
    nodes = [
        *branch("a", "be"),
        Node("g", "a-be", NodeKind.ITEM, "a", "be", "Модуль"),
        leaf("l1", "g", "a", "be", "60-90-120", type_name="Функция"),
        leaf("l2", "a-be", "a", "be", "1-2-30", n=3, type_name="Экран"),
        leaf("l3", "a-be", "a", "be", "0-0-0"),
        leaf("l4", "a-be", "a", "be", None, type_name="Экран"),
        *branch("a", "qa"),
        leaf("l5", "a-qa", "a", "qa", "30-30-30", n=4, type_name="Тест-набор"),
    ]
    return calculate(project(nodes, level=level, pm="10"))


@pytest.mark.spec("6.6")
def test_shares() -> None:
    result = _project()
    sh = shares(result)
    total = sum((v for v in sh.disciplines.values() if v is not None), D(0))
    assert abs(total - 100) < D("1e-30")
    assert sh.by_phase["a"]["qa"] == sh.disciplines["qa"]
    assert sh.phases["a"] is not None
    assert sh.phases["a"] < 100
    empty = calculate(project([]))
    assert shares(empty).disciplines == {"be": None, "qa": None}
    assert shares(empty).phases == {"a": None}


@pytest.mark.spec("6.6")
@pytest.mark.parametrize(
    ("bounds", "verdict"),
    [
        (("10", "20"), Verdict.ABOVE),
        (("200", "300"), Verdict.BELOW),
        (("0", "500"), Verdict.WITHIN),
    ],
)
def test_control_ratio(bounds: tuple[str, str], verdict: Verdict) -> None:
    cr = control_ratio(_project(), "qa", ["be", "unknown"], D(bounds[0]), D(bounds[1]))
    assert cr.verdict is verdict
    assert cr.disciplines_b == ("be", "unknown")


def test_control_ratio_without_hours_in_b() -> None:
    cr = control_ratio(_project(), "missing", ["missing-too"], D(25), D(35))
    assert cr.pct is None
    assert cr.verdict is None


@pytest.mark.spec("10.1")
def test_volumes() -> None:
    found = volumes(_project())
    assert found == {"Функция": 1, "Экран": 4, "Работа": 1, "Тест-набор": 4}  # группа не считается
    assert volumes_text({"Экран": 13, "Функция": 2}) == "Экран — 13, Функция — 2"


@pytest.mark.spec("BR-TREE-09")
@pytest.mark.spec("C-27")
def test_decomposition_levels() -> None:
    medium = decomposition(_project())
    assert medium.threshold_hours == 80
    assert medium.large == ["l1"]  # E_ед = 90 > 80
    assert medium.repeating == ["l5"]  # 4 × 30 = 120 > 80, E_ед = 30
    assert medium.wide_forks == ["l2"]  # σ/E = 4,83/7,17
    assert [c.node_id for c in medium.top_by_e] == ["l5", "l1", "l2", "l3"]
    assert [c.node_id for c in medium.top_by_sigma_ratio] == ["l2", "l1", "l5"]  # 0–0–0 без σ/E
    coarse = decomposition(_project(DetailLevel.COARSE))
    assert coarse.threshold_hours is None
    assert coarse.large == []
    assert coarse.repeating == []
    custom = decomposition(_project(), {DetailLevel.MEDIUM: D(100)})
    assert custom.large == []
    assert custom.repeating == ["l5"]


def test_large_leaf_threshold_defaults() -> None:
    assert large_leaf_threshold(DetailLevel.DETAILED) == 40
    assert large_leaf_threshold(DetailLevel.COARSE, {}) is None
