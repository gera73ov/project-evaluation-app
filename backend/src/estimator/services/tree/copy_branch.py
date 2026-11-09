"""CORE-024 · копирование ветки из другого проекта (SPEC FR-PRJ-03, BR-ROLE-06, Q-44, BR-TREE-05/06;
15.2 ``POST /nodes/{id}/copy-from``).

Источник — узел другого проекта той же дисциплины, права на источник проверяет вызывающий
(``branch.copy_from`` с ``as_source``: только текущий участник, M3.4-09). Ветка дисциплины
копируется своими детьми, узел — вместе с поддеревом; копии встают последними детьми выбранного
узла. Копируются названия, типы, O/R/P, ×N, комментарии; локальный тип источника переносится в
проект-приёмник (тип с тем же названием переиспользуется). Лимиты проверяются до копирования —
при превышении не копируется ничего.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeAction, NodeKind, NodeTypeProposal
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.services.common import emit, user_ref
from estimator.services.review import marks
from estimator.services.trash.batch import live_subtree
from estimator.services.tree.edit import depth_below_branch, history, invalid, work_type
from estimator.services.tree.load import DEPTH_LIMIT, NODES_LIMIT, count_live_nodes, node_event
from estimator.services.tree.positions import keys_after
from estimator.services.tree.structure import Outcome, touch_branch


def _height(nodes: list[Node], roots: set[uuid.UUID]) -> int:
    level: dict[uuid.UUID, int] = {}
    for n in nodes:  # родители раньше детей (live_subtree)
        level[n.id] = 1 if n.id in roots else level.get(n.parent_id, 0) + 1  # type: ignore[arg-type]
    return max(level.values(), default=0)


async def _type_mapper(
    db: AsyncSession, source: Project, target: Project, principal: Principal
) -> Callable[[uuid.UUID | None], Awaitable[uuid.UUID]]:
    """Тип узла источника → тип в проекте-приёмнике (выключенный или чужой — «Работа»)."""
    cache: dict[uuid.UUID, uuid.UUID] = {}
    fallback = await work_type(db)

    async def resolve(type_id: uuid.UUID | None) -> uuid.UUID:
        if type_id is None:
            return fallback
        if type_id in cache:
            return cache[type_id]
        row = await db.get(NodeType, type_id)
        result = fallback
        if row is not None and row.project_id is None:
            result = row.id if row.is_active else fallback
        elif row is not None and row.project_id == source.id:
            same = await db.scalar(
                select(NodeType.id).where(
                    NodeType.project_id == target.id,
                    NodeType.name == row.name,
                    NodeType.proposal_status != NodeTypeProposal.MERGED,
                )
            )
            if same is None:
                copy = NodeType(
                    id=uuid7(),
                    name=row.name,
                    icon=row.icon,
                    norms=[],
                    project_id=target.id,
                    proposal_status=NodeTypeProposal.PROPOSED,
                    created_by=principal.user_id,
                    updated_by=principal.user_id,
                )
                db.add(copy)
                await db.flush()
                same = copy.id
            result = same
        cache[type_id] = result
        return result

    return resolve


async def copy_from(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    target: Node,
    source_project: Project,
    source: Node,
) -> Outcome:
    """Скопировать ветку (узел) ``source`` детьми узла ``target`` (FR-PRJ-03)."""
    if target.kind is NodeKind.PHASE:
        raise invalid("id", "Копировать можно в ветку дисциплины или в узел")
    if source.kind is NodeKind.PHASE or source_project.id == project.id:
        raise invalid("source_node_id", "Выберите ветку или узел другого проекта")
    if source.discipline_id != target.discipline_id:
        raise invalid("source_node_id", "Ветка источника — другой дисциплины")
    if any(getattr(target, k) is not None for k in ("o", "r", "p")) or target.multiplier != 1:
        raise invalid("id", "У листа есть оценка: разбейте его (BR-TREE-02)")

    subtree = await live_subtree(db, source)
    if source.kind is NodeKind.DISCIPLINE:
        subtree = subtree[1:]
        roots = {n.id for n in subtree if n.parent_id == source.id}
    else:
        roots = {source.id}
    if not subtree:
        raise invalid("source_node_id", "В ветке источника нет узлов")
    current = await count_live_nodes(db, project.id)
    if current + len(subtree) > NODES_LIMIT:
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=len(subtree))
    if await depth_below_branch(db, target) + _height(subtree, roots) > DEPTH_LIMIT:
        raise ApiError("DEPTH_LIMIT", max_depth=DEPTH_LIMIT)

    last = await db.scalar(
        select(Node.position)
        .where(Node.parent_id == target.id, Node.deleted_at.is_(None))
        .order_by(Node.position.desc())
        .limit(1)
    )
    root_positions = iter(keys_after(last, len(roots)))
    resolve = await _type_mapper(db, source_project, project, principal)
    author = user_ref(principal.user_id, principal.full_name)
    ids: dict[uuid.UUID, uuid.UUID] = {}
    out = Outcome()
    for n in subtree:
        is_root = n.id in roots
        copy = Node(
            id=uuid7(),
            project_id=project.id,
            parent_id=target.id if is_root else ids[n.parent_id],  # type: ignore[index]
            kind=NodeKind.ITEM,
            phase_id=target.phase_id,
            discipline_id=target.discipline_id,
            type_id=await resolve(n.type_id),
            title=n.title,
            position=next(root_positions) if is_root else n.position,
            o=n.o,
            r=n.r,
            p=n.p,
            multiplier=n.multiplier,
            comment_lines=list(n.comment_lines) if n.comment_lines else None,
            self_review=False,
            version=1,
            field_versions={},
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
        ids[n.id] = copy.id
        db.add(copy)
        await db.flush()
        version = await emit(
            db, project.id, "node.created", {"node": node_event(copy), "author": author}
        )
        created: dict[str, tuple[Any, Any]] = {
            "title": (None, copy.title),
            "type": (None, copy.type_id),
            "copied_from": (None, n.id),
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

    ancestors = [target, *await marks.ancestors(db, target)]
    await marks.clear(db, principal, ancestors)
    out.touched(ancestors)
    await touch_branch(db, principal, project, (target.phase_id, target.discipline_id), out)
    return out
