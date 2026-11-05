"""CORE-007 · TC-CALC-02: свойства свёртки на случайных деревьях (Hypothesis)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from estimator.domain.calc import (
    BranchStatus,
    DetailLevel,
    Discipline,
    Node,
    NodeKind,
    Phase,
    ProjectInput,
    QuoteFigure,
    calculate,
    estimate,
)

HALF_STEPS = st.integers(min_value=0, max_value=2 * 2000).map(lambda v: Decimal(v) / 2)
TOLERANCE = Decimal("1e-25")


def close(a: Decimal, b: Decimal) -> bool:
    """Равенство с относительным допуском: тест сравнивает 40-значные результаты модуля."""
    return abs(a - b) <= TOLERANCE * max(Decimal(1), abs(a), abs(b))


@st.composite
def orp(draw: st.DrawFn) -> tuple[Decimal, Decimal, Decimal]:
    values = sorted(draw(st.lists(HALF_STEPS, min_size=3, max_size=3)))
    return values[0], values[1], values[2]


@st.composite
def trees(draw: st.DrawFn) -> ProjectInput:
    """Фаза → ветка → случайное поддерево глубиной до 4 с листьями (часть — пустые)."""
    nodes = [
        Node("ph", None, NodeKind.PHASE, "ph"),
        Node("br", "ph", NodeKind.DISCIPLINE, "ph", "d"),
    ]
    parents = ["br"]
    for index in range(draw(st.integers(min_value=1, max_value=25))):
        parent = draw(st.sampled_from(parents))
        o, r, p = draw(orp())
        empty = draw(st.booleans()) and draw(st.booleans())
        node = Node(
            f"n{index}",
            parent,
            NodeKind.ITEM,
            "ph",
            "d",
            o=None if empty else o,
            r=r,
            p=p,
            multiplier=draw(st.integers(min_value=1, max_value=10_000)),
        )
        nodes.append(node)
        if len(parents) < 8:
            parents.append(node.id)
    return ProjectInput(
        pm_percent=Decimal(draw(st.integers(min_value=0, max_value=100))) / 2,
        quote_figure=QuoteFigure.P80,
        detail_level=DetailLevel.MEDIUM,
        phases=[Phase("ph", "Разработка"), Phase("pm", "УП", is_cross_cutting=True)],
        disciplines=[Discipline("d", "Бэкенд")],
        nodes=nodes,
        branch_status={("ph", "d"): BranchStatus.DRAFT},
    )


@pytest.mark.tc("TC-CALC-02")
@settings(max_examples=150, deadline=None)
@given(trees())
def test_rollup_properties(project: ProjectInput) -> None:
    """ΣE детей = E узла; σ узла ≤ Σσ детей; P80 ≥ E (TC-CALC-02)."""
    result = calculate(project)
    tree = result.tree
    for node_id, node in tree.nodes.items():
        kids = [tree[c] for c in tree.children.get(node_id, [])]
        if not kids:
            continue
        assert close(node.totals.e, sum((k.totals.e for k in kids), Decimal(0)))
        sigma_sum = sum((k.totals.sigma for k in kids), Decimal(0))
        assert node.totals.sigma <= sigma_sum or close(node.totals.sigma, sigma_sum)
        assert node.totals.p80 >= node.totals.e
        assert node.totals.p90 >= node.totals.p80
    assert result.total.p80 >= result.total.e
    assert close(result.total.e, result.works.e + result.pm.e)


@pytest.mark.tc("TC-CALC-02")
@settings(max_examples=150, deadline=None)
@given(orp(), st.integers(min_value=1, max_value=10_000))
def test_multiplier_scales_linearly(values: tuple[Decimal, Decimal, Decimal], n: int) -> None:
    """×N масштабирует E и σ линейно (TC-CALC-02, 6.1)."""
    one = estimate(*values, 1)
    many = estimate(*values, n)
    assert close(many.e, n * one.e)
    assert close(many.sigma, n * one.sigma)
