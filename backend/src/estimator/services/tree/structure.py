"""CORE-016 · структурные операции над деревом (SPEC FR-TREE-23, BR-TREE-02, BR-TREE-03, 5.1,
BR-BR-02, FR-REV-02; 15.2 ``POST /nodes/{id}/move|split|collapse|duplicate``; TC-TREE-01).

* **Перенос и порядок** (:func:`move_node`): новый родитель и место среди его детей (``after_id``;
  без него — первым). Перенос в другую ветку (пара «фаза × дисциплина») проверяет вызывающий по
  праву ``tree.move.cross_branch``. Смена родителя сбрасывает «готово» и снимает «Проверено» с
  перенесённого поддерева и с предков на старом и новом месте; перестановка внутри родителя
  («Вверх/вниз», перетаскивание) цифр не меняет и ничего не сбрасывает.
* **Разбиение** (:func:`split_node`): лист становится узлом, единственный ребёнок «<название> —
  часть 1» получает прежние O/R/P/×N; E узла не меняется; прежняя оценка — в истории (``split``).
* **Сворачивание** (:func:`collapse_node`): узел становится листом с O/R/P = суммы листьев поддерева
  с учётом ×N (или значениями из запроса), ×N = 1; дети уходят в корзину одним пакетом.
* **Дублирование** (:func:`duplicate_node`): копия поддерева сразу под узлом — названия, типы,
  O/R/P, ×N, комментарии; без «Проверено», истории и обсуждений.

Каждое изменение узла — своё событие со своей версией проекта (одна версия — одно событие).
Толкования — agents/journal/DEC-20261109-core-structure.md.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeAction, NodeKind
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.realtime.locks import iface as locks
from estimator.services.branches.status import touch
from estimator.services.common import emit, user_ref
from estimator.services.review import marks
from estimator.services.trash.batch import live_subtree, trash
from estimator.services.tree.edit import (
    TITLE_MAX,
    depth_below_branch,
    field_conflicts,
    has_live_children,
    history,
    invalid,
    place,
    round_hours,
)
from estimator.services.tree.load import (
    DEPTH_LIMIT,
    NODES_LIMIT,
    compute,
    count_live_nodes,
    node_event,
)
from estimator.services.tree.positions import key_between

SPLIT_SUFFIX = " — часть 1"
ESTIMATE = ("o", "r", "p", "multiplier")


@dataclass
class Outcome:
    """Итог операции: изменённые и созданные узлы, удалённые в корзину, смены статусов веток."""

    node_ids: list[uuid.UUID] = field(default_factory=list)
    deleted_ids: list[uuid.UUID] = field(default_factory=list)
    batch_id: uuid.UUID | None = None
    branch_statuses: list[dict[str, Any]] = field(default_factory=list)
    rounded: list[str] = field(default_factory=list)

    def touched(self, nodes: list[Node]) -> None:
        for n in nodes:
            if n.id not in self.node_ids:
                self.node_ids.append(n.id)


def _only_item(node: Node, action: str) -> None:
    if node.kind is not NodeKind.ITEM:
        raise invalid("id", f"{action}: строки фазы и ветки дисциплины не подходят")


def _has_estimate(node: Node) -> bool:
    return node.o is not None or node.r is not None or node.p is not None or node.multiplier != 1


async def _check_conflicts(
    db: AsyncSession, node: Node, principal: Principal, base_version: int, keys: set[str]
) -> None:
    conflicts = await field_conflicts(db, node, principal, base_version, keys)
    if conflicts:
        raise ApiError("FIELD_CONFLICT", conflicts=conflicts, current_version=node.version)


def _unreview(node: Node, versions: dict[str, Any], changes: dict[str, tuple[Any, Any]]) -> bool:
    """Снять «Проверено» с узла в той же версии, что и правка (FR-REV-02)."""
    if node.reviewed_by is None:
        return False
    node.reviewed_by, node.reviewed_at, node.self_review = None, None, False
    versions["review"] = node.version
    changes["review"] = (True, False)
    return True


async def touch_branch(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    branch: tuple[uuid.UUID, uuid.UUID | None],
    out: Outcome,
) -> None:
    phase_id, discipline_id = branch
    if discipline_id is None:  # pragma: no cover — CHECK item_branch
        return
    change = await touch(db, principal, project.id, phase_id, discipline_id, resets_done=True)
    if change is not None:
        out.branch_statuses.append(change)


# --- перенос и порядок --------------------------------------------------------------------------


def is_cross_branch(node: Node, new_parent: Node) -> bool:
    """Перенос в другую ветку «фаза × дисциплина» (5.1: эксперту запрещён)."""
    return (node.phase_id, node.discipline_id) != (new_parent.phase_id, new_parent.discipline_id)


async def _previous_sibling(db: AsyncSession, node: Node) -> uuid.UUID | None:
    return await db.scalar(
        select(Node.id)
        .where(
            Node.parent_id == node.parent_id,
            Node.deleted_at.is_(None),
            Node.position < node.position,
        )
        .order_by(Node.position.desc())
        .limit(1)
    )


def _height(subtree: list[Node]) -> int:
    """Число уровней поддерева (сам узел — 1)."""
    level: dict[uuid.UUID, int] = {subtree[0].id: 1}
    for n in subtree[1:]:
        if n.parent_id is not None:
            level[n.id] = level[n.parent_id] + 1
    return max(level.values())


async def move_node(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    node: Node,
    new_parent: Node,
    after_id: uuid.UUID | None,
    base_version: int,
) -> Outcome:
    """Перенести узел к ``new_parent`` сразу за ``after_id`` (FR-TREE-23)."""
    _only_item(node, "Перенос")
    if new_parent.project_id != project.id or new_parent.kind is NodeKind.PHASE:
        raise invalid("new_parent_id", "Переносить можно в ветку дисциплины или в узел")
    subtree = await live_subtree(db, node)
    if new_parent.id in {n.id for n in subtree}:
        raise invalid("new_parent_id", "Узел нельзя перенести внутрь самого себя")
    same_parent = new_parent.id == node.parent_id
    if not same_parent and _has_estimate(new_parent):
        raise invalid("new_parent_id", "У листа есть оценка: разбейте его (BR-TREE-02)")
    if after_id == node.id:
        raise invalid("after_id", "Узел не может стоять за самим собой")
    await _check_conflicts(db, node, principal, base_version, {"parent"})
    out = Outcome()
    if same_parent and await _previous_sibling(db, node) == after_id:
        return out  # уже на этом месте
    if not same_parent and await depth_below_branch(db, new_parent) + _height(subtree) > (
        DEPTH_LIMIT
    ):
        raise ApiError("DEPTH_LIMIT", max_depth=DEPTH_LIMIT)

    position = await place(db, new_parent.id, after_id, exclude=node.id)
    old_parent_id = node.parent_id
    old_ancestors = await marks.ancestors(db, node)
    cross = is_cross_branch(node, new_parent)
    old_branch = (node.phase_id, node.discipline_id)
    changes: dict[str, tuple[Any, Any]] = {
        "parent": (old_parent_id, new_parent.id),
        "position": (node.position, position),
    }
    if cross:
        changes["phase_id"] = (node.phase_id, new_parent.phase_id)
        changes["discipline_id"] = (node.discipline_id, new_parent.discipline_id)
    node.parent_id = new_parent.id
    node.position = position
    node.version += 1
    node.field_versions = dict(node.field_versions) | {"parent": node.version}
    node.updated_by = principal.user_id
    author = user_ref(principal.user_id, principal.full_name)

    async def moved(n: Node, from_parent: uuid.UUID | None, diff: Mapping[str, Any]) -> None:
        await db.flush()
        version = await emit(
            db,
            project.id,
            "node.moved",
            {"node": node_event(n), "from_parent_id": str(from_parent), "author": author},
        )
        db.add(history(n, principal, version, NodeAction.MOVE, diff))

    for n in subtree:
        if cross:
            n.phase_id, n.discipline_id = new_parent.phase_id, new_parent.discipline_id
    await moved(node, old_parent_id, changes)
    if cross:  # потомки сменили ветку: у каждого своя версия и событие
        for n in subtree[1:]:
            n.version += 1
            n.updated_by = principal.user_id
            await moved(n, n.parent_id, {k: changes[k] for k in ("phase_id", "discipline_id")})
    out.touched(subtree)
    out.touched(old_ancestors)
    if same_parent:
        return out  # «Вверх/вниз» цифр не меняет (BR-BR-02)

    new_ancestors = [new_parent, *await marks.ancestors(db, new_parent)]
    out.touched(new_ancestors)
    await marks.clear(db, principal, [*subtree, *old_ancestors, *new_ancestors])
    await touch_branch(db, principal, project, old_branch, out)
    if cross:
        await touch_branch(db, principal, project, (node.phase_id, node.discipline_id), out)
    return out


# --- разбиение ----------------------------------------------------------------------------------


def split_title(title: str) -> str:
    """BR-TREE-02: «<название> — часть 1», исходное название обрезается до 200 символов итога."""
    return title[: TITLE_MAX - len(SPLIT_SUFFIX)] + SPLIT_SUFFIX


async def split_node(
    db: AsyncSession, principal: Principal, project: Project, node: Node, base_version: int
) -> Outcome:
    """Разбить лист: узел без оценки и один ребёнок с прежними O/R/P/×N (BR-TREE-02)."""
    _only_item(node, "Разбиение")
    if await has_live_children(db, node.id):
        raise invalid("id", "Разбить можно только лист")
    if await depth_below_branch(db, node) + 1 > DEPTH_LIMIT:
        raise ApiError("DEPTH_LIMIT", max_depth=DEPTH_LIMIT)
    current = await count_live_nodes(db, project.id)
    if current + 1 > NODES_LIMIT:
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=1)
    await _check_conflicts(db, node, principal, base_version, set(ESTIMATE))
    for key in ("o", "r", "p", "multiplier"):
        await locks.assert_not_locked(project.id, node.id, key, user_id=principal.user_id)

    before = {key: getattr(node, key) for key in ESTIMATE}
    child = Node(
        id=uuid7(),
        project_id=project.id,
        parent_id=node.id,
        kind=NodeKind.ITEM,
        phase_id=node.phase_id,
        discipline_id=node.discipline_id,
        type_id=node.type_id,
        title=split_title(node.title),
        position=key_between(None, None),
        o=before["o"],
        r=before["r"],
        p=before["p"],
        multiplier=before["multiplier"],
        comment_lines=None,
        self_review=False,
        version=1,
        field_versions={},
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    changes: dict[str, tuple[Any, Any]] = {
        k: (v, None) for k, v in before.items() if k != "multiplier" and v is not None
    }
    if before["multiplier"] != 1:
        changes["multiplier"] = (before["multiplier"], 1)
    node.o = node.r = node.p = None
    node.multiplier = 1
    node.version += 1
    versions = dict(node.field_versions) | dict.fromkeys(changes, node.version)
    _unreview(node, versions, changes)
    node.field_versions = versions
    node.updated_by = principal.user_id
    changes["child_id"] = (None, child.id)
    author = user_ref(principal.user_id, principal.full_name)
    await db.flush()
    version = await emit(
        db,
        project.id,
        "node.updated",
        {
            "node": node_event(node),
            "author": author,
            "changed_fields": sorted(k for k in changes if k != "child_id"),
        },
    )
    db.add(history(node, principal, version, NodeAction.SPLIT, changes))

    db.add(child)
    await db.flush()
    version = await emit(
        db, project.id, "node.created", {"node": node_event(child), "author": author}
    )
    created: dict[str, tuple[Any, Any]] = {
        "title": (None, child.title),
        "type": (None, child.type_id),
    }
    created |= {k: (None, before[k]) for k in ("o", "r", "p") if before[k] is not None}
    if child.multiplier != 1:
        created["multiplier"] = (1, child.multiplier)
    db.add(history(child, principal, version, NodeAction.CREATE, created))

    ancestors = await marks.ancestors(db, node)
    await marks.clear(db, principal, ancestors)
    out = Outcome(node_ids=[node.id, child.id])
    out.touched(ancestors)
    await touch_branch(db, principal, project, (node.phase_id, node.discipline_id), out)
    return out


# --- сворачивание -------------------------------------------------------------------------------


async def collapse_suggestion(db: AsyncSession, project: Project, node: Node) -> dict[str, Any]:
    """BR-TREE-03: O/R/P = суммы N·O, N·R, N·P листьев поддерева, ×N = 1."""
    computed = await compute(db, project)
    s = computed.result.tree.collapse_suggestion(str(node.id))
    return {
        "o": format_decimal(s.o),
        "r": format_decimal(s.r),
        "p": format_decimal(s.p),
        "multiplier": 1,
    }


async def collapse_node(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    node: Node,
    base_version: int,
    values: Mapping[str, str | None],
) -> Outcome:
    """Свернуть узел в лист; дети — в корзину одним пакетом (BR-TREE-03)."""
    _only_item(node, "Сворачивание")
    children = (
        await db.scalars(
            select(Node)
            .where(Node.parent_id == node.id, Node.deleted_at.is_(None))
            .order_by(Node.position)
        )
    ).all()
    if not children:
        raise invalid("id", "Свернуть можно только узел с детьми")
    await _check_conflicts(db, node, principal, base_version, {*ESTIMATE, "parent"})
    suggestion = await collapse_suggestion(db, project, node)
    out = Outcome()
    hours: dict[str, Decimal] = {}
    for key in ("o", "r", "p"):
        raw = values.get(key)
        hours[key], changed = round_hours(raw if raw is not None else suggestion[key], key)
        if changed and raw is not None:
            out.rounded.append(key)

    out.batch_id, out.deleted_ids = await trash(db, principal, project.id, children)
    changes: dict[str, tuple[Any, Any]] = {k: (getattr(node, k), v) for k, v in hours.items()}
    node.o, node.r, node.p = hours["o"], hours["r"], hours["p"]
    node.multiplier = 1
    node.version += 1
    versions = dict(node.field_versions) | dict.fromkeys(changes, node.version)
    _unreview(node, versions, changes)
    node.field_versions = versions
    node.updated_by = principal.user_id
    await db.flush()
    version = await emit(
        db,
        project.id,
        "node.updated",
        {
            "node": node_event(node),
            "author": user_ref(principal.user_id, principal.full_name),
            "changed_fields": sorted(changes),
        },
    )
    changes["deleted_batch_id"] = (None, out.batch_id)
    db.add(history(node, principal, version, NodeAction.COLLAPSE, changes))

    ancestors = await marks.ancestors(db, node)
    await marks.clear(db, principal, ancestors)
    out.node_ids.append(node.id)
    out.touched(ancestors)
    await touch_branch(db, principal, project, (node.phase_id, node.discipline_id), out)
    return out


# --- дублирование -------------------------------------------------------------------------------


async def duplicate_node(
    db: AsyncSession, principal: Principal, project: Project, node: Node
) -> Outcome:
    """Копия узла с поддеревом сразу под ним (FR-TREE-23)."""
    _only_item(node, "Дублирование")
    parent = await db.get(Node, node.parent_id)
    if parent is None:  # pragma: no cover — у узла дерева всегда есть родитель
        raise invalid("id", "Нет родителя")
    subtree = await live_subtree(db, node)
    current = await count_live_nodes(db, project.id)
    if current + len(subtree) > NODES_LIMIT:
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=len(subtree))
    next_position = await db.scalar(
        select(Node.position)
        .where(
            Node.parent_id == node.parent_id,
            Node.deleted_at.is_(None),
            Node.position > node.position,
        )
        .order_by(Node.position)
        .limit(1)
    )
    author = user_ref(principal.user_id, principal.full_name)
    copies: dict[uuid.UUID, uuid.UUID] = {}
    out = Outcome()
    for source in subtree:
        root = source.id == node.id
        copy = Node(
            id=uuid7(),
            project_id=project.id,
            parent_id=node.parent_id if root else copies[source.parent_id],  # type: ignore[index]
            kind=NodeKind.ITEM,
            phase_id=source.phase_id,
            discipline_id=source.discipline_id,
            type_id=source.type_id,
            title=source.title,
            position=key_between(node.position, next_position) if root else source.position,
            o=source.o,
            r=source.r,
            p=source.p,
            multiplier=source.multiplier,
            comment_lines=list(source.comment_lines) if source.comment_lines else None,
            self_review=False,
            version=1,
            field_versions={},
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
        copies[source.id] = copy.id
        db.add(copy)
        await db.flush()
        version = await emit(
            db, project.id, "node.created", {"node": node_event(copy), "author": author}
        )
        created: dict[str, tuple[Any, Any]] = {
            "title": (None, copy.title),
            "type": (None, copy.type_id),
        }
        created |= {
            k: (None, getattr(copy, k)) for k in ("o", "r", "p") if getattr(copy, k) is not None
        }
        if copy.multiplier != 1:
            created["multiplier"] = (1, copy.multiplier)
        if copy.comment_lines:
            created["comment"] = (None, copy.comment_lines)
        db.add(history(copy, principal, version, NodeAction.CREATE, created))
        out.node_ids.append(copy.id)

    ancestors = [parent, *await marks.ancestors(db, parent)]
    await marks.clear(db, principal, ancestors)
    out.touched(ancestors)
    await touch_branch(db, principal, project, (node.phase_id, node.discipline_id), out)
    return out
