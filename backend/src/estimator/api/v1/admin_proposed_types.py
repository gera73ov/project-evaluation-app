"""Предложенные типы (ADM-009; SPEC FR-TREE-03, 7.5; contracts/openapi.yaml
``/admin/proposed-types``). Право ``proposed_types.manage`` (администратор)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path, Response

from estimator.admin import proposed_types as service
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.api.v1.core_schemas import NodeType
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
TypeId = Annotated[uuid.UUID, Path(alias="id")]
PERMISSION = "proposed_types.manage"


@router.get(
    "/admin/proposed-types",
    permission=PERMISSION,
    response_model=s.ProposedTypeList,
    response_model_exclude_unset=True,
)
async def list_proposed_types(db: DbSession) -> dict[str, Any]:
    return {"items": await service.list_proposed(db)}


@router.post("/admin/proposed-types/{id}/accept", permission=PERMISSION, response_model=NodeType)
async def accept_proposed_type(
    principal: ActivePrincipal, db: DbSession, type_id: TypeId
) -> dict[str, Any]:
    return await service.accept(db, principal, type_id)


@router.post("/admin/proposed-types/{id}/merge", permission=PERMISSION, response_model=NodeType)
async def merge_proposed_type(
    body: s.MergeRequest, principal: ActivePrincipal, db: DbSession, type_id: TypeId
) -> dict[str, Any]:
    return await service.merge(db, principal, type_id, body.target_type_id)


@router.post("/admin/proposed-types/{id}/reject", permission=PERMISSION, status_code=204)
async def reject_proposed_type(
    principal: ActivePrincipal, db: DbSession, type_id: TypeId
) -> Response:
    await service.reject(db, principal, type_id)
    return Response(status_code=204)
