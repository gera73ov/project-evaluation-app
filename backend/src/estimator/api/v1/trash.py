"""Корзина проекта (CORE-017; contracts/openapi.yaml ``GET /projects/{id}/trash``,
``POST /trash/{batch_id}/restore``; SPEC FR-TREE-24, GAP-06).

Объект ``/trash/{batch_id}`` для gate — проект и дисциплина пакета (:func:`trash_target`):
эксперт видит и восстанавливает только пакеты своих веток (scope ``own_discipline``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.api.v1.nodes import _nodes_response, _project
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import NodeKind, ProjectRole
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.tree import Node
from estimator.db.session import DbSession
from estimator.security.authz import Target
from estimator.security.authz.deps import register_resolver
from estimator.services.trash import listing
from estimator.services.trash import nodes as trash_nodes
from estimator.services.tree.moderator_edits import notify_experts

router = ApiRouter(tags=["Дерево"])


async def trash_target(db: AsyncSession, batch_id: uuid.UUID) -> Target | None:
    """Пакет корзины → проект, статус и дисциплина корня; пакеты веток дисциплин — 404."""
    rows = (
        await db.execute(
            select(
                Node.id, Node.parent_id, Node.kind, Node.discipline_id, Project.id, Project.status
            )
            .join(Project, Project.id == Node.project_id)
            .where(Node.deleted_batch_id == batch_id)
        )
    ).all()
    ids = {r[0] for r in rows}
    roots = [r for r in rows if r[1] not in ids]
    if not roots or any(r[2] is not NodeKind.ITEM for r in roots):
        return None
    _, _, _, discipline_id, project_id, status = roots[0]
    return Target(
        project_id=project_id,
        project_status=str(status),
        disciplines=frozenset({discipline_id}) if discipline_id else frozenset(),
    )


register_resolver("/trash/{id}", trash_target)


async def _expert_disciplines(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = await db.scalars(
        select(ProjectMember.discipline_id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role == ProjectRole.EXPERT,
        )
    )
    return {d for d in rows.all() if d is not None}


@router.get(
    "/projects/{id}/trash",
    permission=["trash.read"],
    response_model=s.TrashList,
    response_model_exclude_unset=True,
)
async def get_trash(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """Модератор видит всё, эксперт — удалённое из своих веток (FR-TREE-24); пресейл — только
    документы (GAP-06), их добавит трек DOC."""
    restricted = request.state.access.restricted
    disciplines: set[uuid.UUID] | None = None
    if "own_discipline" in restricted:
        disciplines = await _expert_disciplines(db, id, principal.user_id)
    elif restricted:
        disciplines = set()
    return {"items": await listing.list_trash(db, id, disciplines)}


@router.post(
    "/trash/{batch_id}/restore",
    permission="trash.restore",
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def restore_trash(
    batch_id: uuid.UUID,
    body: s.TrashRestore,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """Восстановить пакет на прежнее место или под ``target_parent_id`` (FR-TREE-24, G-15)."""
    batch = await trash_nodes.batch_nodes(db, batch_id)
    if not batch:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    project = await _project(db, batch[0].project_id)
    out = await trash_nodes.restore_batch(db, principal, project, batch, body.target_parent_id)
    root = batch[0]
    await notify_experts(db, principal, project.id, root.id, root.discipline_id, ["structure"])
    return await _nodes_response(db, project.id, out)
