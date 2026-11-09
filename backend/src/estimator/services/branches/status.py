"""CORE-018 · статус ветки дисциплины (SPEC 4.3, BR-BR-01…03, FR-NOTIF-01; 15.2
``PUT /projects/{id}/branches/{phase}/{discipline}/status``).

Ручные переходы (:func:`set_status`), стрелки диаграммы 4.3:

* «черновик» → «готово» — эксперт дисциплины или модератор, только без пустых и неверных листьев
  (иначе 409 ``BRANCH_NOT_READY`` с ``node_ids``);
* «не начато» → «не нужно», «черновик» → «не нужно» — модератор, только пустая ветка (иначе 409
  ``BRANCH_NOT_EMPTY``); «не нужно» → «не начато» — модератор.

Остальные пары — 409 ``INVALID_TRANSITION``.

Автоматические переходы при правке дерева (:func:`touch`, BR-BR-02): первая правка — «не начато» →
«черновик»; правка O/R/P, ×N и структуры — «готово» → «черновик» с уведомлением
``branch_back_to_draft`` модераторам проекта и экспертам дисциплины (кроме автора). Переименование,
смена типа и комментарий статус не меняют. Снятие «Проверено» — CORE-019.

Каждая смена — событие ``branch.status`` со своей версией проекта.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue, NodeKind, ProjectRole
from estimator.db.models.projects import BranchStatus, Project, ProjectMember
from estimator.db.models.tree import Node
from estimator.domain.calc import LeafState
from estimator.notifications import inapp
from estimator.services.common import emit, user_ref
from estimator.services.tree.load import compute

S = BranchStatusValue

#: Ручные переходы: (было, стало) → право (диаграмма 4.3)
MANUAL: Mapping[tuple[BranchStatusValue, BranchStatusValue], str] = {
    (S.DRAFT, S.DONE): "branch.status.draft_done",
    (S.NOT_STARTED, S.NOT_NEEDED): "branch.status.not_needed",
    (S.DRAFT, S.NOT_NEEDED): "branch.status.not_needed",
    (S.NOT_NEEDED, S.NOT_STARTED): "branch.status.not_needed",
}


def permission_for(was: BranchStatusValue, to: BranchStatusValue) -> str:
    """Право на ручной переход; нет стрелки — 409 ``INVALID_TRANSITION``."""
    code = MANUAL.get((was, to))
    if code is None:
        raise ApiError("INVALID_TRANSITION", **{"from": was.value, "to": to.value})
    return code


async def branch_node(
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


async def _subtree(db: AsyncSession, project: Project, root: Node) -> tuple[list[Any], Any]:
    """Живые узлы ветки (с корнем) и расчёт проекта."""
    computed = await compute(db, project)
    children: dict[uuid.UUID | None, list[Any]] = {}
    for n in computed.nodes:
        children.setdefault(n.parent_id, []).append(n)
    out: list[Any] = []
    stack = [n for n in computed.nodes if n.id == root.id]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(children.get(node.id, []))
    return out, computed.result


async def not_ready_leaves(db: AsyncSession, project: Project, root: Node) -> list[uuid.UUID]:
    """BR-BR-01: листья ветки с пустой оценкой или с нарушением O ≤ R ≤ P."""
    nodes, result = await _subtree(db, project, root)
    bad = []
    for n in nodes:
        calc_node = result.tree[str(n.id)]
        leaf = calc_node.leaf
        if (
            calc_node.is_leaf
            and leaf is not None
            and leaf.state
            in (
                LeafState.EMPTY,
                LeafState.INVALID,
            )
        ):
            bad.append(n.id)
    return bad


async def _apply(
    db: AsyncSession,
    principal: Principal,
    row: BranchStatus,
    new: BranchStatusValue,
) -> dict[str, Any]:
    was = row.status
    row.status = new
    row.changed_by = principal.user_id
    row.changed_at = dt.datetime.now(dt.UTC)
    change = {
        "phase_id": str(row.phase_id),
        "discipline_id": str(row.discipline_id),
        "status": new.value,
        "was": was.value,
    }
    await emit(
        db,
        row.project_id,
        "branch.status",
        change | {"author": user_ref(principal.user_id, principal.full_name)},
    )
    return change


async def set_status(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    row: BranchStatus,
    to: BranchStatusValue,
) -> dict[str, Any]:
    """Ручной переход (права проверены вызывающим по :func:`permission_for`)."""
    permission_for(row.status, to)
    root = await branch_node(db, project.id, row.phase_id, row.discipline_id)
    if root is None:
        raise ApiError("NOT_FOUND")
    if to is S.DONE:
        bad = await not_ready_leaves(db, project, root)
        if bad:
            raise ApiError(
                "BRANCH_NOT_READY",
                detail=f"В ветке есть листья без оценки или с ошибкой: {len(bad)}",
                node_ids=[str(i) for i in bad],
            )
    if to is S.NOT_NEEDED:
        has_children = await db.scalar(
            select(Node.id).where(Node.parent_id == root.id, Node.deleted_at.is_(None)).limit(1)
        )
        if (
            has_children is not None
            or root.o is not None
            or root.r is not None
            or root.p is not None
        ):
            raise ApiError("BRANCH_NOT_EMPTY")
    return await _apply(db, principal, row, to)


async def _notify_back_to_draft(db: AsyncSession, principal: Principal, row: BranchStatus) -> None:
    """``branch_back_to_draft``: модераторам проекта и экспертам дисциплины, кроме автора."""
    members = (
        await db.execute(
            select(ProjectMember.user_id, ProjectMember.role, ProjectMember.discipline_id).where(
                ProjectMember.project_id == row.project_id
            )
        )
    ).all()
    recipients = {
        user_id
        for user_id, role, discipline_id in members
        if role is ProjectRole.MODERATOR
        or (role is ProjectRole.EXPERT and discipline_id == row.discipline_id)
    }
    await inapp.notify(
        db,
        "branch_back_to_draft",
        recipients,
        project_id=row.project_id,
        payload={
            "project_id": str(row.project_id),
            "phase_id": str(row.phase_id),
            "discipline_id": str(row.discipline_id),
            "actor_id": str(principal.user_id),
        },
        actor_id=principal.user_id,
    )


async def touch(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    phase_id: uuid.UUID,
    discipline_id: uuid.UUID,
    *,
    resets_done: bool,
) -> dict[str, Any] | None:
    """Статус ветки после правки (BR-BR-02); изменение (``BranchStatusChange``) или ``None``."""
    row = await db.get(BranchStatus, (project_id, phase_id, discipline_id))
    if row is None:
        return None
    if row.status is S.NOT_STARTED:
        return await _apply(db, principal, row, S.DRAFT)
    if resets_done and row.status is S.DONE:
        change = await _apply(db, principal, row, S.DRAFT)
        await _notify_back_to_draft(db, principal, row)
        return change
    return None
