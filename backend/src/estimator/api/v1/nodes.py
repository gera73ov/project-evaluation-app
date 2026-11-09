"""Создание и правка узлов (CORE-015; contracts/openapi.yaml ``POST /projects/{id}/nodes``,
``PATCH /nodes/{id}``; пример ответа — SPEC 15.3).

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
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep, Target
from estimator.security.authz.deps import register_resolver
from estimator.services.review import marks
from estimator.services.tree import edit
from estimator.services.tree.load import load_tree, mutation_view

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
) -> dict[str, Any]:
    """Ответ 15.3: узел, предки с новыми E и σ, итог проекта, статус ветки."""
    await db.flush()
    project = await _project(db, project_id)
    node, ancestors, totals = await mutation_view(db, project, node_id)
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
    return await _response(db, project.id, node.id, branch, rounded)


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
    node, branch, rounded = await edit.patch_node(
        db, principal, project, node, body.base_version, changes
    )
    return await _response(db, project.id, node.id, branch, rounded)


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
    await db.flush()
    project = await _project(db, node.project_id)
    tree = await load_tree(db, project)
    ids = {str(i) for i in changed}
    return {
        "nodes": [n for n in tree["nodes"] if n["id"] in ids],
        "project_version": project.version,
        "totals": tree["totals"]["total"],
        "branch_statuses": [],
    }
