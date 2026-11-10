"""Дерево проекта целиком (CORE-014; contracts/openapi.yaml «Дерево», ``GET /projects/{id}/tree``).

Ответ без денег (SEC-AUTHZ-04). Право ``tree.read`` проверяет gate ``ApiRouter``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.services.tree.load import load_tree

router = ApiRouter(tags=["Дерево"])


@router.get(
    "/projects/{id}/tree",
    permission="tree.read",
    response_model=s.Tree,
    response_model_exclude_unset=True,
)
async def get_tree(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await db.get(Project, id)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return await load_tree(db, project, principal.user_id)
