"""CORE-003/004 · инкрементальный пересчёт (NFR-PERF-03): после любой цепочки правок, созданий
и переносов узлов состояние совпадает с полным расчётом того же дерева."""

from __future__ import annotations

from dataclasses import replace
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
    TreeError,
    calculate,
)
from estimator.domain.calc.incremental import CalcState, build, refresh
from tests.unit.core.calc.test_properties import close, orp

pytestmark = pytest.mark.spec("NFR-PERF-03")

PHASES = [
    Phase("a", "Анализ"),
    Phase("b", "Разработка", in_pm_base=False),
    Phase("off", "Выключена", enabled=False),
    Phase("pm", "УП", is_cross_cutting=True),
]
DISCIPLINES = [Discipline("be", "Бэкенд"), Discipline("qa", "QA")]


def _base() -> list[Node]:
    nodes = [Node(p.id, None, NodeKind.PHASE, p.id) for p in PHASES]
    for p in ("a", "b", "off"):
        nodes += [Node(f"{p}-{d.id}", p, NodeKind.DISCIPLINE, p, d.id) for d in DISCIPLINES]
    return nodes


def _project(nodes: list[Node]) -> ProjectInput:
    return ProjectInput(
        pm_percent=Decimal(18),
        quote_figure=QuoteFigure.P80,
        detail_level=DetailLevel.MEDIUM,
        phases=PHASES,
        disciplines=DISCIPLINES,
        nodes=nodes,
        branch_status={("b", "qa"): BranchStatus.NOT_NEEDED},
    )


def _item(draw: st.DrawFn, node_id: str, parent: Node) -> Node:
    o, r, p = draw(orp())
    empty = draw(st.integers(min_value=0, max_value=4)) == 0
    return Node(
        node_id,
        parent.id,
        NodeKind.ITEM,
        parent.phase_id,
        parent.discipline_id,
        o=None if empty else o,
        r=r,
        p=p,
        multiplier=draw(st.integers(min_value=1, max_value=20)),
    )


def _subtree(nodes: dict[str, Node], root: str) -> set[str]:
    out = {root}
    grew = True
    while grew:
        grew = False
        for n in nodes.values():
            if n.parent_id in out and n.id not in out:
                out.add(n.id)
                grew = True
    return out


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[list[Node], list[list[Node]]]:
    """Начальное дерево и шаги; шаг — узлы, переданные в один вызов :func:`refresh`."""
    nodes = {n.id: n for n in _base()}
    parents = [n for n in nodes.values() if n.kind is NodeKind.DISCIPLINE]
    for i in range(draw(st.integers(min_value=0, max_value=20))):
        node = _item(draw, f"n{i}", draw(st.sampled_from(parents)))
        nodes[node.id] = node
        parents.append(node)
    initial = list(nodes.values())
    steps: list[list[Node]] = []
    counter = 100
    for _ in range(draw(st.integers(min_value=1, max_value=8))):
        step: dict[str, Node] = {}
        for _ in range(draw(st.integers(min_value=1, max_value=3))):
            items = [n for n in nodes.values() if n.kind is NodeKind.ITEM]
            action = draw(st.sampled_from(["update", "create", "move"] if items else ["create"]))
            if action == "create":
                counter += 1
                parent = draw(st.sampled_from([n for n in nodes.values() if n.parent_id]))
                node = _item(draw, f"n{counter}", parent)
            elif action == "update":
                old = draw(st.sampled_from(items))
                fresh = _item(draw, old.id, nodes[old.parent_id or ""])
                node = replace(old, o=fresh.o, r=fresh.r, p=fresh.p, multiplier=fresh.multiplier)
            else:
                old = draw(st.sampled_from(items))
                banned = _subtree(nodes, old.id)
                targets = [n for n in nodes.values() if n.parent_id and n.id not in banned]
                parent = draw(st.sampled_from(targets))
                node = replace(
                    old,
                    parent_id=parent.id,
                    phase_id=parent.phase_id,
                    discipline_id=parent.discipline_id,
                )
            nodes[node.id] = node
            step[node.id] = node
        steps.append(list(step.values()))
    return initial, steps


def _assert_same(state: CalcState, *, exact: bool) -> None:
    nodes = [r.node for r in state.tree.nodes.values()]
    full = calculate(_project(nodes))
    same = (lambda a, b: a == b) if exact else close
    assert state.tree.children.keys() == full.tree.children.keys()
    for parent, kids in full.tree.children.items():
        assert sorted(state.tree.children[parent]) == sorted(kids)
    for node_id, want in full.tree.nodes.items():
        got = state.tree[node_id]
        assert (got.node, got.is_leaf, got.excluded) == (want.node, want.is_leaf, want.excluded)
        assert got.leaf == want.leaf
        assert got.totals.unaccounted == want.totals.unaccounted
        for field in ("e", "sigma_sq", "sum_o", "sum_r", "sum_p"):
            assert same(getattr(got.totals, field), getattr(want.totals, field)), (node_id, field)
    summary = state.summary
    assert summary.unaccounted_leaves == full.unaccounted_leaves
    assert summary.phases.keys() == full.phases.keys()
    pairs = [(summary.works, full.works), (summary.pm, full.pm), (summary.total, full.total)]
    pairs += [(summary.phases[k], full.phases[k]) for k in full.phases]
    for got_f, want_f in pairs:
        assert same(got_f.e, want_f.e)
        assert same(got_f.sigma, want_f.sigma)


@settings(max_examples=150, deadline=None)
@given(scenarios())
def test_refresh_matches_full_calculation(scenario: tuple[list[Node], list[list[Node]]]) -> None:
    initial, steps = scenario
    state = build(_project(initial))
    _assert_same(state, exact=True)
    moved = False
    for step in steps:
        before = {i: r.node.parent_id for i, r in state.tree.nodes.items()}
        moved = moved or any(n.id in before and before[n.id] != n.parent_id for n in step)
        previous = state
        state = refresh(state, step)
        # без переносов порядок соседей тот же, что у полного расчёта, — совпадение знак в знак
        _assert_same(state, exact=not moved)
        assert previous.tree.nodes is not state.tree.nodes  # старое состояние не тронуто


def test_refresh_keeps_previous_state() -> None:
    nodes = [*_base(), Node("x", "a-be", NodeKind.ITEM, "a", "be", o=Decimal(1), r=Decimal(2),
                            p=Decimal(3))]  # fmt: skip
    state = build(_project(nodes))
    child = Node("y", "x", NodeKind.ITEM, "a", "be", o=Decimal(4), r=Decimal(4), p=Decimal(4))
    after = refresh(state, [child])
    assert state.tree["x"].is_leaf
    assert not after.tree["x"].is_leaf  # лист стал группой
    assert state.tree.children.get("x") is None
    assert after.summary.works.e == Decimal(4)
    assert state.summary.works.e == Decimal(2)
    assert refresh(after, []).summary == after.summary


def test_refresh_rejects_missing_parent_and_cycle() -> None:
    nodes = [*_base(), Node("x", "a-be", NodeKind.ITEM, "a", "be"),
             Node("y", "x", NodeKind.ITEM, "a", "be")]  # fmt: skip
    state = build(_project(nodes))
    with pytest.raises(TreeError, match="нет родителя"):
        refresh(state, [Node("z", "ghost", NodeKind.ITEM, "a", "be")])
    with pytest.raises(TreeError, match="цикл"):
        refresh(state, [Node("x", "y", NodeKind.ITEM, "a", "be")])
