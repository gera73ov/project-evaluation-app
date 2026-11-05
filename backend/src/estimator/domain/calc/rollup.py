"""CORE-003 · свёртка дерева (SPEC 6.2, BR-CALC-01, BR-CALC-02, BR-TREE-03, FR-TREE-10, R-08).

``E_узла = ΣE детей``, ``σ_узла = √Σσ²``, подсказка ``ΣN·O / ΣN·R / ΣN·P``. Пустые и неверные
листья в суммы не входят и считаются как «не учтено». Ветки «не нужно» и выключенные фазы в
суммах предков не участвуют (их собственные суммы считаются, но помечены ``excluded``).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from estimator.domain.calc._decimal import ZERO, in_calc_context, p80, p90, sqrt
from estimator.domain.calc.leaf import LeafEstimate, estimate
from estimator.domain.calc.model import BranchStatus, Node, NodeKind, ProjectInput


@dataclass(slots=True)
class Totals:
    """Суммы по поддереву. σ хранится квадратом: так суммы складываются без потери точности."""

    e: Decimal = ZERO
    sigma_sq: Decimal = ZERO
    sum_o: Decimal = ZERO
    sum_r: Decimal = ZERO
    sum_p: Decimal = ZERO
    unaccounted: int = 0  # листья без оценки или с неверной оценкой (BR-CALC-02)

    def add(self, other: Totals) -> None:
        self.e += other.e
        self.sigma_sq += other.sigma_sq
        self.sum_o += other.sum_o
        self.sum_r += other.sum_r
        self.sum_p += other.sum_p
        self.unaccounted += other.unaccounted

    @property
    def sigma(self) -> Decimal:
        return sqrt(self.sigma_sq)

    @property
    def p80(self) -> Decimal:
        return p80(self.e, self.sigma)

    @property
    def p90(self) -> Decimal:
        return p90(self.e, self.sigma)


@dataclass(slots=True)
class NodeResult:
    node: Node
    is_leaf: bool
    excluded: bool  # ветка «не нужно» или выключенная фаза (BR-CALC-01)
    leaf: LeafEstimate | None
    totals: Totals = field(default_factory=Totals)


@dataclass(frozen=True, slots=True)
class CollapseSuggestion:
    """Предложение «Свернуть в лист» (BR-TREE-03): суммы детей с учётом ×N, ×N = 1."""

    o: Decimal
    r: Decimal
    p: Decimal
    multiplier: int = 1


class TreeError(ValueError):
    """Дерево собрано неверно: нет родителя, цикл."""


@dataclass(slots=True)
class TreeResult:
    nodes: dict[str, NodeResult]
    children: dict[str | None, list[str]]

    def __getitem__(self, node_id: str) -> NodeResult:
        return self.nodes[node_id]

    def leaves(self, *, include_excluded: bool = False) -> Iterator[NodeResult]:
        """Листья в порядке обхода дерева (порядок соседей — как во входе)."""
        for node_id in self.walk():
            result = self.nodes[node_id]
            if result.is_leaf and (include_excluded or not result.excluded):
                yield result

    def walk(self) -> Iterator[str]:
        """Прямой обход (родитель раньше детей)."""
        stack = list(reversed(self.children.get(None, [])))
        while stack:
            node_id = stack.pop()
            yield node_id
            stack.extend(reversed(self.children.get(node_id, [])))

    def collapse_suggestion(self, node_id: str) -> CollapseSuggestion:
        totals = self.nodes[node_id].totals
        return CollapseSuggestion(totals.sum_o, totals.sum_r, totals.sum_p)


def _children(nodes: Sequence[Node]) -> dict[str | None, list[str]]:
    ids = {n.id for n in nodes}
    children: dict[str | None, list[str]] = {}
    for node in nodes:
        if node.parent_id is not None and node.parent_id not in ids:
            raise TreeError(f"у узла {node.id} нет родителя {node.parent_id}")
        children.setdefault(node.parent_id, []).append(node.id)
    return children


def _is_excluded(
    node: Node,
    disabled_phases: set[str],
    branch_status: Mapping[tuple[str, str], BranchStatus],
) -> bool:
    if node.phase_id in disabled_phases:
        return True
    if node.discipline_id is None:
        return False
    return branch_status.get((node.phase_id, node.discipline_id)) is BranchStatus.NOT_NEEDED


@in_calc_context
def rollup(project: ProjectInput) -> TreeResult:
    """Посчитать листья и суммы всех узлов дерева."""
    children = _children(project.nodes)
    disabled = {p.id for p in project.phases if not p.enabled}
    results: dict[str, NodeResult] = {}
    for node in project.nodes:
        is_leaf = node.kind is NodeKind.ITEM and node.id not in children
        leaf = estimate(node.o, node.r, node.p, node.multiplier) if is_leaf else None
        excluded = _is_excluded(node, disabled, project.branch_status)
        result = NodeResult(node, is_leaf, excluded, leaf)
        if leaf is not None:
            _leaf_totals(result.totals, leaf)
        results[node.id] = result
    tree = TreeResult(results, children)
    order = list(tree.walk())
    if len(order) != len(results):
        raise TreeError("в дереве есть цикл")
    for node_id in reversed(order):  # дети раньше родителей
        result = results[node_id]
        parent_id = result.node.parent_id
        if parent_id is None:
            continue
        parent = results[parent_id]
        # граница исключения: ветка «не нужно» не попадает в фазу, а внутри себя сворачивается
        if not result.excluded or parent.excluded:
            parent.totals.add(result.totals)
    return tree


def _leaf_totals(totals: Totals, leaf: LeafEstimate) -> None:
    if not leaf.state.counted:
        totals.unaccounted = 1
        return
    totals.e = leaf.e
    totals.sigma_sq = leaf.sigma * leaf.sigma
    totals.sum_o = leaf.sum_o
    totals.sum_r = leaf.sum_r
    totals.sum_p = leaf.sum_p
