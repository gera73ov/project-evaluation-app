"""CORE-017 · удаление узлов в корзину и восстановление (SPEC FR-TREE-24, BR-TREE-03, BR-TREE-05/06,
BR-BR-02, 3.4; 15.2 ``DELETE /nodes/{id}``, ``POST /trash/{batch_id}/restore``).

* Удаление — узел со всем живым поддеревом одним пакетом (:func:`batch.trash`); «готово» →
  «черновик», «Проверено» снимается с родителя и предков.
* Восстановление возвращает пакет на прежнее место. Удалённые предки корня восстанавливаются вместе
  с ним (только сами предки, без остальных узлов их пакетов); удалённая ветка дисциплины заменяется
  живой веткой той же пары «фаза × дисциплина».
* Место недоступно (дисциплина удалена из проекта, фаза выключена, ветка «не нужно») — 409
  ``RESTORE_TARGET_UNAVAILABLE`` с ``reason`` и ``discipline_id``; клиент повторяет запрос с
  ``target_parent_id`` — узлом той же дисциплины.
* Лист с оценкой, под который возвращаются дети (пакет «Свернуть в лист» или лист, которому
  оценку поставили после удаления детей), теряет O/R/P/×N — они остаются в истории (BR-TREE-01).
* Лимиты BR-TREE-05/06 проверяются до записи. Восстановление — событие ``node.restored``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue, NodeAction, NodeKind
from estimator.db.models.projects import BranchStatus, Project, ProjectDiscipline, ProjectPhase
from estimator.db.models.tree import Node
from estimator.services.common import emit, user_ref
from estimator.services.review import marks
from estimator.services.trash.batch import trash
from estimator.services.tree.edit import depth_below_branch, history, invalid, place
from estimator.services.tree.load import DEPTH_LIMIT, NODES_LIMIT, count_live_nodes, node_event
from estimator.services.tree.structure import Outcome, touch_branch

ESTIMATE = ("o", "r", "p", "multiplier")


async def delete_node(
    db: AsyncSession, principal: Principal, project: Project, node: Node
) -> Outcome:
    """Удалить узел с поддеревом в корзину (FR-TREE-24)."""
    if node.kind is not NodeKind.ITEM:
        # 422 у DELETE в контракте нет: строка фазы и ветка — не объект корзины, отказ как в праве
        raise ApiError(
            "FORBIDDEN", detail="Ветку убирают «Удалить дисциплину», строку фазы — настройки фаз"
        )
    parent = await db.get(Node, node.parent_id)
    if parent is None:  # pragma: no cover — у узла дерева всегда есть родитель
        raise invalid("id", "Нет родителя")
    out = Outcome()
    out.batch_id, out.deleted_ids = await trash(db, principal, project.id, [node])
    ancestors = [parent, *await marks.ancestors(db, parent)]
    await marks.clear(db, principal, ancestors)
    out.touched(ancestors)
    await touch_branch(db, principal, project, (node.phase_id, node.discipline_id), out)
    return out


# --- восстановление -----------------------------------------------------------------------------


async def batch_nodes(db: AsyncSession, batch_id: uuid.UUID) -> list[Node]:
    return list(
        (
            await db.scalars(
                select(Node)
                .where(Node.deleted_batch_id == batch_id)
                .order_by(Node.position)
                .with_for_update()
            )
        ).all()
    )


async def _unavailable(
    db: AsyncSession, project_id: uuid.UUID, phase_id: uuid.UUID, discipline_id: uuid.UUID
) -> str | None:
    """Почему ветка «фаза × дисциплина» не принимает узлы (FR-TREE-24); ``None`` — принимает."""
    in_project = await db.scalar(
        select(
            exists().where(
                ProjectDiscipline.project_id == project_id,
                ProjectDiscipline.discipline_id == discipline_id,
            )
        )
    )
    if not in_project:
        return "discipline_removed"
    enabled = await db.scalar(
        select(ProjectPhase.is_enabled).where(
            ProjectPhase.project_id == project_id, ProjectPhase.phase_id == phase_id
        )
    )
    if enabled is False:
        return "phase_disabled"
    status = await db.scalar(
        select(BranchStatus.status).where(
            BranchStatus.project_id == project_id,
            BranchStatus.phase_id == phase_id,
            BranchStatus.discipline_id == discipline_id,
        )
    )
    if status is BranchStatusValue.NOT_NEEDED:
        return "branch_not_needed"
    return None


async def _live_branch(
    db: AsyncSession, project_id: uuid.UUID, phase_id: uuid.UUID, discipline_id: uuid.UUID
) -> Node | None:
    return await db.scalar(
        select(Node).where(
            Node.project_id == project_id,
            Node.phase_id == phase_id,
            Node.discipline_id == discipline_id,
            Node.kind == NodeKind.DISCIPLINE,
            Node.deleted_at.is_(None),
        )
    )


async def _original_place(db: AsyncSession, root: Node) -> tuple[Node | None, list[Node]]:
    """Живой узел, под который вернётся корень, и удалённые предки между ними (сверху вниз)."""
    path: list[Node] = []
    parent = await db.get(Node, root.parent_id) if root.parent_id else None
    while parent is not None and parent.deleted_at is not None:
        if parent.kind is not NodeKind.ITEM:
            if parent.discipline_id is None:  # pragma: no cover — фазы не удаляются
                return None, []
            parent = await _live_branch(db, root.project_id, parent.phase_id, parent.discipline_id)
            break
        path.append(parent)
        parent = await db.get(Node, parent.parent_id) if parent.parent_id else None
    return parent, list(reversed(path))


def _height(nodes: list[Node], roots: list[Node]) -> int:
    level = {r.id: 1 for r in roots}
    pending = [n for n in nodes if n.id not in level]
    while pending:
        rest = []
        for n in pending:
            if n.parent_id in level:
                level[n.id] = level[n.parent_id] + 1  # type: ignore[index]
            else:
                rest.append(n)
        if len(rest) == len(pending):  # pragma: no cover — пакет всегда связен
            break
        pending = rest
    return max(level.values())


async def _clear_estimate(
    db: AsyncSession, principal: Principal, project: Project, leaf: Node, out: Outcome
) -> None:
    """Лист снова становится узлом: O/R/P/×N уходят в историю (BR-TREE-01, BR-TREE-03)."""
    changes: dict[str, tuple[Any, Any]] = {
        k: (getattr(leaf, k), None) for k in ("o", "r", "p") if getattr(leaf, k) is not None
    }
    if leaf.multiplier != 1:
        changes["multiplier"] = (leaf.multiplier, 1)
    leaf.o = leaf.r = leaf.p = None
    leaf.multiplier = 1
    leaf.version += 1
    leaf.field_versions = dict(leaf.field_versions) | dict.fromkeys(changes, leaf.version)
    leaf.updated_by = principal.user_id
    await db.flush()
    version = await emit(
        db,
        project.id,
        "node.updated",
        {
            "node": node_event(leaf),
            "author": user_ref(principal.user_id, principal.full_name),
            "changed_fields": sorted(changes),
        },
    )
    db.add(history(leaf, principal, version, NodeAction.UPDATE, changes))
    out.touched([leaf])


def _has_estimate(node: Node) -> bool:
    return any(getattr(node, k) is not None for k in ("o", "r", "p")) or node.multiplier != 1


async def restore_batch(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    nodes: list[Node],
    target_parent_id: uuid.UUID | None,
) -> Outcome:
    """Восстановить пакет корзины; ``target_parent_id`` — другое место в той же дисциплине."""
    batch_id = nodes[0].deleted_batch_id
    ids = {n.id for n in nodes}
    roots = [n for n in nodes if n.parent_id not in ids]
    root = roots[0]
    if root.discipline_id is None:  # pragma: no cover — резолвер не отдаёт такие пакеты
        raise ApiError("NOT_FOUND")
    path: list[Node] = []
    if target_parent_id is None:
        attach, path = await _original_place(db, root)
        reason = (
            "discipline_removed"
            if attach is None
            else await _unavailable(db, project.id, attach.phase_id, root.discipline_id)
        )
        if reason is not None:
            raise ApiError(
                "RESTORE_TARGET_UNAVAILABLE", reason=reason, discipline_id=str(root.discipline_id)
            )
    else:
        attach = await db.get(Node, target_parent_id, populate_existing=True)
        if (
            attach is None
            or attach.deleted_at is not None
            or attach.project_id != project.id
            or attach.kind is NodeKind.PHASE
            or attach.discipline_id != root.discipline_id
        ):
            raise invalid("target_parent_id", "Выберите узел той же дисциплины в проекте")
        if _has_estimate(attach):
            raise invalid("target_parent_id", "У листа есть оценка: разбейте его (BR-TREE-02)")
        reason = await _unavailable(db, project.id, attach.phase_id, root.discipline_id)
        if reason is not None:
            raise ApiError(
                "RESTORE_TARGET_UNAVAILABLE", reason=reason, discipline_id=str(root.discipline_id)
            )
    if attach is None:  # pragma: no cover — выше ответили 409
        raise ApiError("NOT_FOUND")

    restoring = [*path, *nodes]
    current = await count_live_nodes(db, project.id)
    if current + len(restoring) > NODES_LIMIT:
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=len(restoring))
    height = len(path) + _height(nodes, roots)
    if await depth_below_branch(db, attach) + height > DEPTH_LIMIT:
        raise ApiError("DEPTH_LIMIT", max_depth=DEPTH_LIMIT)

    out = Outcome()
    if _has_estimate(attach):  # пакет «Свернуть в лист» или оценка после удаления детей
        await _clear_estimate(db, principal, project, attach, out)
    top = path[0] if path else None
    moved: dict[uuid.UUID, tuple[Any, Any]] = {}
    if top is not None and top.parent_id != attach.id:
        moved[top.id] = (top.parent_id, attach.id)
    if top is None and target_parent_id is not None:
        for r in roots:
            moved[r.id] = (r.parent_id, attach.id)
    before: dict[uuid.UUID, tuple[Any, Any, Any, Any]] = {}
    for n in restoring:
        before[n.id] = (n.parent_id, n.position, n.phase_id, n.deleted_batch_id)
        if n.id in moved:
            n.parent_id = attach.id
            n.position = await place(db, attach.id, None)
        n.phase_id = attach.phase_id
        n.deleted_at = n.deleted_batch_id = n.deleted_by = None
        n.version += 1
        n.updated_by = principal.user_id
    await db.flush()
    version = await emit(
        db,
        project.id,
        "node.restored",
        {
            "nodes": [node_event(n) for n in restoring],
            "batch_id": str(batch_id),
            "author": user_ref(principal.user_id, principal.full_name),
        },
    )
    for n in restoring:
        old_parent, old_position, old_phase, old_batch = before[n.id]
        changes: dict[str, tuple[Any, Any]] = {"deleted_batch_id": (old_batch, None)}
        if n.id in moved:
            n.field_versions = dict(n.field_versions) | {"parent": n.version}
            changes["parent"] = (old_parent, n.parent_id)
            changes["position"] = (old_position, n.position)
        if old_phase != n.phase_id:
            changes["phase_id"] = (old_phase, n.phase_id)
        db.add(history(n, principal, version, NodeAction.RESTORE, changes))
    out.touched(restoring)
    ancestors = [attach, *await marks.ancestors(db, attach)]
    await marks.clear(db, principal, ancestors)
    out.touched(ancestors)
    await touch_branch(db, principal, project, (attach.phase_id, root.discipline_id), out)
    return out
