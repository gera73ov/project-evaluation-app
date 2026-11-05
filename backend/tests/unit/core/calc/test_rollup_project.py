"""CORE-003, CORE-004 · свёртка, исключения веток и фаз, УП и итог (SPEC 6.2, 6.3)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from estimator.domain.calc import (
    BranchStatus,
    Node,
    NodeKind,
    Phase,
    TreeError,
    calculate,
    rollup,
)
from estimator.domain.calc.project import unaccounted_text

from ._build import branch, leaf, project

D = Decimal


@pytest.mark.spec("BR-CALC-01")
def test_not_needed_branch_is_excluded_but_keeps_own_sums() -> None:
    nodes = [
        *branch("a", "be"),
        leaf("l1", "a-be", "a", "be", "8-12-20"),
        *branch("a", "qa"),
        leaf("l2", "a-qa", "a", "qa", "4-6-8"),
        leaf("l3", "a-qa", "a", "qa", None),
    ]
    result = calculate(project(nodes, status={("a", "qa"): BranchStatus.NOT_NEEDED}))
    assert result.tree["a-qa"].excluded
    assert result.tree["a-qa"].totals.e == D(6)  # своя сумма ветки считается
    assert result.tree["a"].totals.e == result.tree["l1"].totals.e
    assert result.disciplines["qa"].e == 0
    assert result.unaccounted_leaves == 0  # пустой лист ветки «не нужно» не в предупреждении
    assert [r.node.id for r in result.tree.leaves()] == ["l1"]
    assert [r.node.id for r in result.tree.leaves(include_excluded=True)] == ["l1", "l2", "l3"]


@pytest.mark.spec("6.3")
def test_disabled_phase_and_cross_cutting_leaves_are_not_works() -> None:
    phases = [
        Phase("a", "Разработка"),
        Phase("w", "Гарантия", in_pm_base=False, enabled=False),
        Phase("pm", "УП", is_cross_cutting=True, in_pm_base=False),
    ]
    nodes = [
        *branch("a", "be"),
        leaf("l1", "a-be", "a", "be", "6-6-6"),
        *branch("w", "be"),
        leaf("l2", "w-be", "w", "be", "60-60-60"),
        *branch("pm", "be"),
        leaf("l3", "pm-be", "pm", "be", "1-1-1"),
        leaf("l4", "pm-be", "pm", "be", None),
    ]
    result = calculate(project(nodes, phases=phases, pm="10"))
    assert result.tree["w"].excluded
    assert result.tree["w"].totals.e == D(60)
    assert list(result.phases) == ["a"]
    assert result.works.e == D(6)
    assert result.disciplines["be"].e == D(6)
    assert result.pm.e == D("0.6")
    assert result.pm.enabled
    assert result.unaccounted_leaves == 1  # пустой лист сквозной фазы виден в предупреждении


def test_phase_without_root_node_counts_as_empty() -> None:
    base = project([], phases=[Phase("a", "Разработка")])
    result = calculate(replace(base, phases=[*base.phases, Phase("x", "Без узла")]))
    assert result.phases["x"].e == 0
    assert not result.pm.enabled


def test_leaf_outside_project_disciplines_is_ignored_in_discipline_rollup() -> None:
    nodes = [*branch("a", "ops"), leaf("l1", "a-ops", "a", "ops", "2-2-2")]
    result = calculate(project(nodes))
    assert result.works.e == D(2)
    assert set(result.disciplines) == {"be", "qa"}


@pytest.mark.spec("BR-CALC-03")
def test_ratios_and_warning() -> None:
    empty = calculate(project([*branch("a", "be"), leaf("l1", "a-be", "a", "be", None)]))
    assert empty.p80_ratio is None
    assert empty.p90_ratio is None
    assert empty.unaccounted_warning() == "1 лист без оценки не учтён"
    full = calculate(project([*branch("a", "be"), leaf("l1", "a-be", "a", "be", "4-6-8")]))
    assert full.p80_ratio is not None
    assert full.p80_ratio > 1
    assert full.p90_ratio is not None
    assert full.p90_ratio > full.p80_ratio
    assert full.unaccounted_warning() is None


@pytest.mark.tc("TC-CALC-03")
@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 лист без оценки не учтён"),
        (3, "3 листа без оценки не учтены"),
        (5, "5 листов без оценки не учтены"),
        (11, "11 листов без оценки не учтены"),
        (12, "12 листов без оценки не учтены"),
        (21, "21 лист без оценки не учтён"),
        (22, "22 листа без оценки не учтены"),
    ],
)
def test_unaccounted_text_plural(count: int, text: str) -> None:
    assert unaccounted_text(count) == text


def test_tree_errors() -> None:
    orphan = project([leaf("l1", "missing", "a", "be", "1-1-1")])
    with pytest.raises(TreeError, match="нет родителя"):
        rollup(orphan)
    cycle = project(
        [
            Node("x", "y", NodeKind.ITEM, "a", "be"),
            Node("y", "x", NodeKind.ITEM, "a", "be"),
        ]
    )
    with pytest.raises(TreeError, match="цикл"):
        rollup(cycle)


def test_walk_order_and_collapse() -> None:
    nodes = [
        *branch("a", "be"),
        Node("g", "a-be", NodeKind.ITEM, "a", "be"),
        leaf("c1", "g", "a", "be", "8-12-20"),
        leaf("c2", "g", "a", "be", "4-6-8", n=2),
        leaf("c3", "g", "a", "be", "9-1-1"),  # неверный — в подсказку не входит
    ]
    tree = rollup(project(nodes))
    assert list(tree.walk()) == ["a", "a-be", "g", "c1", "c2", "c3", "pm"]
    s = tree.collapse_suggestion("g")
    assert (s.o, s.r, s.p, s.multiplier) == (D(16), D(24), D(36), 1)
    assert tree["g"].totals.unaccounted == 1
