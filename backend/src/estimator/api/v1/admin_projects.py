"""Реестр проектов администратора и режим поддержки (ADM-010, ADM-011; SPEC 7.5, BR-PRJ-07,
BR-ADM-03, FR-ADM-06; contracts/openapi.yaml ``/admin/projects``)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path, Query

from estimator.admin import registry, support
from estimator.admin.registry import admin as admin_registry
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.api.v1 import core_schemas as cs
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import ProjectStatus
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
SCOPE = "admin.projects"
ProjectId = Annotated[uuid.UUID, Path(alias="id")]


@router.get(
    "/admin/projects",
    permission="registry.read",
    response_model=s.RegistryList,
    response_model_exclude_unset=True,
)
async def admin_registry_list(
    db: DbSession,
    page: PageParams,
    without_moderator: Annotated[bool | None, Query()] = None,
    status: Annotated[ProjectStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    filt = registry.Filter(q=q, status=status, without_moderator=without_moderator)
    items, nxt = await registry.page(db, filt, after=page.position(SCOPE), limit=page.limit)
    return {"items": items, "next_cursor": encode_cursor(SCOPE, nxt) if nxt else None}


@router.post(
    "/admin/projects/{id}/moderators",
    permission="project.moderators.transfer",
    response_model=cs.MemberList,
    response_model_exclude_unset=True,
)
async def transfer_moderators(
    body: s.ModeratorsTransfer, principal: ActivePrincipal, db: DbSession, project_id: ProjectId
) -> dict[str, Any]:
    items = await admin_registry.transfer_moderators(
        db, principal, project_id, add=body.add_user_ids, remove=body.remove_user_ids
    )
    return {"items": items}


@router.post(
    "/admin/projects/{id}/support-session",
    permission="support.open",
    status_code=201,
    response_model=s.SupportSession,
)
async def open_support_session(
    body: s.SupportSessionCreate, principal: ActivePrincipal, db: DbSession, project_id: ProjectId
) -> dict[str, Any]:
    return await support.open_session(db, principal, project_id, body.reason)
