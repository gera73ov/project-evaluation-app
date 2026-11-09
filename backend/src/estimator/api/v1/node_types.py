"""Типы узлов проекта (CORE-020, CR-006; contracts/openapi.yaml ``GET/POST
/projects/{id}/node-types``). Права ``tree.read`` и ``node_type.create_local`` проверяет gate
``ApiRouter``, статус проекта — тоже он (409 ``PROJECT_STATUS_CONFLICT``)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.services.tree import local_types

router = ApiRouter(tags=["Проекты"])


@router.get("/projects/{id}/node-types", permission="tree.read", response_model=s.NodeTypeList)
async def list_project_node_types(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    return {"items": await local_types.project_types(db, id)}


@router.post(
    "/projects/{id}/node-types",
    permission="node_type.create_local",
    status_code=201,
    response_model=s.NodeType,
)
async def create_local_node_type(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.LocalNodeType,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await db.get(Project, id)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return await local_types.create_local(db, principal, project, body.name, body.icon)
