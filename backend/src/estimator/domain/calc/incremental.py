"""CORE-003/004 · инкрементальный пересчёт: изменились несколько узлов — пересчитать только их
и предков (SPEC 6.2, 6.3, 15.3; NFR-PERF-03).

:func:`build` — полная свёртка один раз (тот же :func:`rollup`). :func:`refresh` принимает новые
строки изменённых или созданных узлов и возвращает новое состояние: пересчитываются эти узлы,
их прежние и новые родители и все предки. Остальные результаты переиспользуются как есть.

Сумма родителя складывается из сумм детей в том же порядке, что у :func:`rollup` (от последнего
ребёнка к первому), а итоги проекта дают общий :func:`summarize`. Поэтому при одинаковом порядке
узлов результат совпадает с полным :func:`calculate` знак в знак — это проверяют тесты.

Состояние не изменяется на месте: :func:`refresh` копирует словари и создаёт новые результаты
только для пересчитанных узлов. Старое состояние остаётся верным для своей версии проекта.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from estimator.domain.calc._decimal import in_calc_context
from estimator.domain.calc.leaf import estimate
from estimator.domain.calc.model import Node, NodeKind, ProjectInput
from estimator.domain.calc.project import Summary, summarize
from estimator.domain.calc.rollup import (
    NodeResult,
    TreeError,
    TreeResult,
    _is_excluded,
    _leaf_totals,
    rollup,
)


@dataclass(frozen=True, slots=True)
class CalcState:
    """Свёртка дерева и итоги проекта для одного набора узлов.

    ``input`` — параметры проекта (фазы, дисциплины, статусы веток, доля УП); его поле ``nodes``
    отражает набор на момент :func:`build` и после :func:`refresh` не обновляется — актуальные
    узлы в ``tree``.
    """

    input: ProjectInput
    tree: TreeResult
    summary: Summary
    #: Кэш представлений для слоя сервиса: ``id → (NodeResult, …)``. Общий у состояния и всех
    #: его потомков от :func:`refresh`; запись годна, пока результат узла тот же объект
    memo: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@in_calc_context
def build(project: ProjectInput) -> CalcState:
    """Полная свёртка: начальное состояние."""
    tree = rollup(project)
    return CalcState(project, tree, summarize(project, tree))


@in_calc_context
def refresh(state: CalcState, changed: Iterable[Node]) -> CalcState:
    """Новое состояние после изменения или создания узлов ``changed`` (удаление не поддержано).

    Узлы с прежним ``parent_id`` остаются на своём месте среди соседей, новый или перенесённый
    узел становится последним ребёнком нового родителя.
    """
    changed_nodes = list(changed)
    nodes = {i: r.node for i, r in state.tree.nodes.items()}
    children = dict(state.tree.children)
    dirty: set[str] = set()
    for node in changed_nodes:
        old = nodes.get(node.id)
        if old is None or old.parent_id != node.parent_id:
            if old is not None:
                children[old.parent_id] = [i for i in children[old.parent_id] if i != node.id]
                if not children[old.parent_id]:
                    del children[old.parent_id]
                dirty.add(_key(old.parent_id))
            children[node.parent_id] = [*children.get(node.parent_id, []), node.id]
            dirty.add(_key(node.parent_id))
        nodes[node.id] = node
        dirty.add(node.id)
    for node in changed_nodes:
        if node.parent_id is not None and node.parent_id not in nodes:
            raise TreeError(f"у узла {node.id} нет родителя {node.parent_id}")
    dirty.discard("")

    depth: dict[str, int] = {}
    for node_id in list(dirty):
        _climb(node_id, nodes, depth, dirty)

    disabled = {p.id for p in state.input.phases if not p.enabled}
    statuses = state.input.branch_status
    results = dict(state.tree.nodes)
    for node_id in sorted(dirty, key=depth.__getitem__, reverse=True):  # дети раньше родителей
        node = nodes[node_id]
        kids = children.get(node_id, [])
        is_leaf = node.kind is NodeKind.ITEM and not kids
        leaf = estimate(node.o, node.r, node.p, node.multiplier) if is_leaf else None
        result = NodeResult(node, is_leaf, _is_excluded(node, disabled, statuses), leaf)
        if leaf is not None:
            _leaf_totals(result.totals, leaf)
        for child_id in reversed(kids):  # порядок сложения — как у rollup
            child = results[child_id]
            if not child.excluded or result.excluded:
                result.totals.add(child.totals)
        results[node_id] = result
    tree = TreeResult(results, children)
    return replace(state, tree=tree, summary=summarize(state.input, tree))


def _key(parent_id: str | None) -> str:
    return "" if parent_id is None else parent_id


def _climb(node_id: str, nodes: dict[str, Node], depth: dict[str, int], dirty: set[str]) -> int:
    """Глубина узла (у корня 0); всех предков — в ``dirty``. Цикл — :class:`TreeError`."""
    path: list[str] = []
    current: str | None = node_id
    while current is not None and current not in depth:
        if len(path) > len(nodes):
            raise TreeError("в дереве есть цикл")
        path.append(current)
        current = nodes[current].parent_id
    base = -1 if current is None else depth[current]
    for i, item in enumerate(reversed(path), start=1):
        depth[item] = base + i
        dirty.add(item)
    return depth[node_id]
