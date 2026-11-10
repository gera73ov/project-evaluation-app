"""Создание, правка и структурные операции узлов (CORE-015, CORE-016, CORE-019;
contracts/openapi.yaml ``POST /projects/{id}/nodes``, ``PATCH /nodes/{id}``,
``POST /nodes/{id}/move|split|collapse|duplicate|review``; пример ответа — SPEC 15.3).

Объект ``/nodes/{id}`` для gate — проект и дисциплина узла (:func:`node_target`): эксперт правит
только свои ветки (scope ``own_discipline``). ``PATCH`` с комментарием требует
``comment.write``, с остальными полями — ``tree.write``; обработчик проверяет оба по составу
``changes``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep, Target
from estimator.security.authz.deps import register_resolver
from estimator.services.review import marks
from estimator.services.trash import nodes as trash_nodes
from estimator.services.tree import copy_branch, edit, structure
from estimator.services.tree import history as node_history
from estimator.services.tree.load import load_tree, mutation_view
from estimator.services.tree.moderator_edits import notify_experts

router = ApiRouter(tags=["Дерево"])


def _target(node: Node, project: Project) -> Target:
    return Target(
        project_id=project.id,
        project_status=str(project.status),
        disciplines=frozenset({node.discipline_id}) if node.discipline_id else frozenset(),
    )


async def node_target(db: AsyncSession, node_id: uuid.UUID) -> Target | None:
    """Объект ``/nodes/{id}``: живой узел → проект, статус и дисциплина; иначе 404."""
    row = (
        await db.execute(
            select(Node.discipline_id, Project.id, Project.status)
            .join(Project, Project.id == Node.project_id)
            .where(Node.id == node_id, Node.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    discipline_id, project_id, status = row
    return Target(
        project_id=project_id,
        project_status=str(status),
        disciplines=frozenset({discipline_id}) if discipline_id else frozenset(),
    )


register_resolver("/nodes/{id}", node_target)


async def _project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


async def _response(
    db: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    branch: dict[str, Any] | None,
    rounded: list[str],
    viewer: uuid.UUID,
) -> dict[str, Any]:
    """Ответ 15.3: узел, предки с новыми E и σ, итог проекта, статус ветки."""
    await db.flush()
    project = await _project(db, project_id)
    node, ancestors, totals = await mutation_view(db, project, node_id, viewer)
    return {
        "node": node,
        "project_version": project.version,
        "ancestors": ancestors,
        "totals": totals,
        "branch_status": branch,
        "rounded": rounded,
    }


@router.post(
    "/projects/{id}/nodes",
    permission="tree.write",
    status_code=201,
    response_model=s.NodeMutation,
    response_model_exclude_unset=True,
)
async def create_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NodeCreate,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await _project(db, id)
    parent = await edit.live_node(db, body.parent_id)
    if parent is None or parent.project_id != project.id:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Родительский узел не найден в проекте",
            errors=[{"field": "/parent_id", "code": "invalid", "message": "Узел не найден"}],
        )
    await authz.check("tree.write", _target(parent, project))
    node, branch, rounded = await edit.create_node(
        db, principal, project, parent, body.model_dump(exclude_unset=True)
    )
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _response(db, project.id, node.id, branch, rounded, principal.user_id)


@router.patch(
    "/nodes/{id}",
    permission=["tree.write", "comment.write"],
    response_model=s.NodeMutation,
    response_model_exclude_unset=True,
)
async def patch_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NodePatch,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    node = await edit.live_node(db, id)
    if node is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    project = await _project(db, node.project_id)
    changes = body.changes.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Нет изменений",
            errors=[{"field": "/changes", "code": "required", "message": "Нет изменений"}],
        )
    target = _target(node, project)
    if changes.keys() - {"comment_lines"}:
        await authz.check("tree.write", target)
    if "comment_lines" in changes:
        await authz.check("comment.write", target)
    was = node.version
    node, branch, rounded = await edit.patch_node(
        db, principal, project, node, body.base_version, changes
    )
    if node.version != was:  # FR-TREE-34: какие поля правка действительно изменила
        fields = [k for k, v in node.field_versions.items() if v == node.version]
        await notify_experts(db, principal, project.id, node.id, node.discipline_id, fields)
    return await _response(db, project.id, node.id, branch, rounded, principal.user_id)


@router.post(
    "/nodes/{id}/review",
    permission="review.mark",
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def review_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NodeReview,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """CORE-019: «Проверено» на узле и поддереве (FR-REV-01, FR-REV-04)."""
    node = await edit.live_node(db, id)
    if node is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    changed = await marks.mark(db, principal, node, body.reviewed)
    return await _nodes_response(
        db, node.project_id, structure.Outcome(node_ids=changed), principal.user_id
    )


async def _nodes_response(
    db: AsyncSession, project_id: uuid.UUID, out: structure.Outcome, viewer: uuid.UUID
) -> dict[str, Any]:
    """``NodesMutation``: изменённые и созданные узлы (с новыми E и σ), удалённые, итог проекта."""
    await db.flush()
    project = await _project(db, project_id)
    tree = await load_tree(db, project, viewer)
    ids = {str(i) for i in out.node_ids}
    body: dict[str, Any] = {
        "nodes": [n for n in tree["nodes"] if n["id"] in ids],
        "project_version": project.version,
        "totals": tree["totals"]["total"],
        "branch_statuses": out.branch_statuses,
    }
    if out.batch_id is not None:
        body["deleted_ids"] = out.deleted_ids
        body["batch_id"] = out.batch_id
    return body


async def _live(db: AsyncSession, node_id: uuid.UUID) -> tuple[Node, Project]:
    node = await edit.live_node(db, node_id)
    if node is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return node, await _project(db, node.project_id)


@router.post(
    "/nodes/{id}/move",
    permission=["tree.write", "tree.move.cross_branch"],
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def move_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NodeMove,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    """Перенос и порядок (FR-TREE-23): эксперт — в своей ветке, модератор — по проекту (5.1)."""
    node, project = await _live(db, id)
    new_parent = await edit.live_node(db, body.new_parent_id)
    if new_parent is None or new_parent.project_id != project.id:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Новый родитель не найден в проекте",
            errors=[{"field": "/new_parent_id", "code": "invalid", "message": "Узел не найден"}],
        )
    await authz.check("tree.write", _target(node, project))
    if structure.is_cross_branch(node, new_parent):
        await authz.check("tree.move.cross_branch", _target(node, project))
        await authz.check("tree.move.cross_branch", _target(new_parent, project))
    from_discipline = node.discipline_id
    out = await structure.move_node(
        db, principal, project, node, new_parent, body.after_id, body.base_version
    )
    if out.node_ids:
        for discipline in {from_discipline, node.discipline_id}:
            await notify_experts(db, principal, project.id, node.id, discipline, ["move"])
    return await _nodes_response(db, project.id, out, principal.user_id)


@router.post(
    "/nodes/{id}/split",
    permission="tree.write",
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def split_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.VersionOnly,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """«Разбить лист» (BR-TREE-02)."""
    node, project = await _live(db, id)
    out = await structure.split_node(db, principal, project, node, body.base_version)
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out, principal.user_id)


@router.get(
    "/nodes/{id}/collapse",
    permission="tree.read",
    response_model=s.CollapseSuggestion,
)
async def collapse_suggestion(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    """Предложение O/R/P для «Свернуть в лист» (BR-TREE-03)."""
    node, project = await _live(db, id)
    return await structure.collapse_suggestion(db, project, node)


@router.post(
    "/nodes/{id}/collapse",
    permission="tree.write",
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def collapse_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NodeCollapse,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """«Свернуть в лист»: дети — в корзину одним пакетом (BR-TREE-03)."""
    node, project = await _live(db, id)
    values = body.model_dump(exclude={"base_version"})
    out = await structure.collapse_node(db, principal, project, node, body.base_version, values)
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out, principal.user_id)


@router.post(
    "/nodes/{id}/duplicate",
    permission="tree.write",
    status_code=201,
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def duplicate_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """«Дублировать» (FR-TREE-23): копия поддерева сразу под узлом."""
    node, project = await _live(db, id)
    out = await structure.duplicate_node(db, principal, project, node)
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out, principal.user_id)


@router.delete(
    "/nodes/{id}",
    permission="tree.write",
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def delete_node(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """Удалить узел с поддеревом в корзину одним пакетом (FR-TREE-24)."""
    node, project = await _live(db, id)
    out = await trash_nodes.delete_node(db, principal, project, node)
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out, principal.user_id)


HISTORY_SCOPE = "node-history"


@router.get(
    "/nodes/{id}/history",
    permission="tree.read",
    response_model=s.HistoryPage,
    response_model_exclude_unset=True,
)
async def get_node_history(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    db: DbSession,
) -> dict[str, Any]:
    """История узла, новые сверху (FR-TREE-25); «Вернуть» — обычный ``PATCH``."""
    after = page.position(HISTORY_SCOPE)
    if after is not None and not (isinstance(after.get("v"), int) and "id" in after):
        raise ApiError("CURSOR_INVALID")
    items, position = await node_history.node_history(db, id, after=after, limit=page.limit)
    return {
        "items": items,
        "next_cursor": encode_cursor(HISTORY_SCOPE, position) if position else None,
    }


@router.post(
    "/nodes/{id}/copy-from",
    permission="branch.copy_from",
    status_code=201,
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def copy_branch_from(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CopyFrom,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    """CORE-024: ветка другого проекта — детьми узла (FR-PRJ-03); источник — только проект, где
    пользователь сейчас участник (BR-ROLE-06, M3.4-09), иначе 404."""
    node, project = await _live(db, id)
    source = await db.get(Node, body.source_node_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    source_project = await _project(db, source.project_id)
    await authz.check(
        "branch.copy_from",
        Target(
            project_id=source_project.id,
            project_status=str(source_project.status),
            disciplines=frozenset({source.discipline_id}) if source.discipline_id else frozenset(),
            as_source=True,
        ),
    )
    out = await copy_branch.copy_from(db, principal, project, node, source_project, source)
    await notify_experts(db, principal, project.id, node.id, node.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out, principal.user_id)
