"""Пользователи в админке администратора (ADM-006; SPEC 7.5, FR-AUTH-LOC-01, FR-2FA-03,
FR-SESS-05, BR-PRJ-07, SEC-AUTHZ-06; contracts/openapi.yaml «Администратор», ``/admin/users``).

Правила — :mod:`estimator.admin.users`. Сбросы пароля и TOTP — со step-up (``x-step-up``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path, Query, Response

from estimator.admin import replace, users
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.auth.context import SessionServiceDep
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import SystemRole, UserStatus
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
SCOPE = "admin.users"
UserId = Annotated[uuid.UUID, Path(alias="id")]


@router.get("/admin/users", permission="users.read", response_model=s.UserList)
async def list_users(
    db: DbSession,
    page: PageParams,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[UserStatus | None, Query()] = None,
    role: Annotated[SystemRole | None, Query()] = None,
) -> dict[str, Any]:
    filt = users.ListFilter(q=q, status=status, role=role)
    items, nxt = await users.list_users(db, filt, after=page.position(SCOPE), limit=page.limit)
    return {"items": items, "next_cursor": encode_cursor(SCOPE, nxt) if nxt else None}


@router.post(
    "/admin/users", permission="users.manage", status_code=201, response_model=s.UserCreated
)
async def create_user(
    body: s.UserCreate, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    user, activation = await users.create_user(
        db, principal, login=body.login, full_name=body.full_name, email=body.email,
        roles=body.roles, ad_object_guid=body.ad_object_guid,
    )  # fmt: skip
    return {"user": user, "activation": activation}


@router.get("/admin/users/{id}", permission="users.read", response_model=s.User)
async def get_user(db: DbSession, user_id: UserId) -> dict[str, Any]:
    return await users.get_user(db, user_id)


@router.patch(
    "/admin/users/{id}", permission=["users.manage", "users.roles.grant"], response_model=s.User
)
async def patch_user(
    body: s.UserPatch, principal: ActivePrincipal, db: DbSession, user_id: UserId
) -> dict[str, Any]:
    return await users.patch_user(db, principal, user_id, body.model_dump(exclude_unset=True))


@router.post(
    "/admin/users/{id}/reset-password",
    permission="users.reset_credentials",
    response_model=s.ActivationLink,
)
async def reset_password(principal: ActivePrincipal, db: DbSession, user_id: UserId) -> Any:
    return await users.reset_password(db, principal, user_id)


@router.post("/admin/users/{id}/reset-totp", permission="users.reset_credentials", status_code=204)
async def reset_totp(
    principal: ActivePrincipal, db: DbSession, sessions: SessionServiceDep, user_id: UserId
) -> Response:
    await users.reset_totp(db, sessions, principal, user_id)
    return Response(status_code=204)


@router.post("/admin/users/{id}/block", permission="users.manage", response_model=s.User)
async def block_user(
    body: s.BlockRequest,
    principal: ActivePrincipal,
    db: DbSession,
    sessions: SessionServiceDep,
    user_id: UserId,
) -> dict[str, Any]:
    del body  # причина — для журнала действий в интерфейсе; в аудит пишется block_reason
    return await users.block_user(db, sessions, principal, user_id)


@router.post("/admin/users/{id}/unblock", permission="users.manage", response_model=s.User)
async def unblock_user(principal: ActivePrincipal, db: DbSession, user_id: UserId) -> Any:
    return await users.unblock_user(db, principal, user_id)


@router.post(
    "/admin/users/{id}/replace",
    permission="users.replace_everywhere",
    response_model=s.ReplaceReport,
)
async def replace_everywhere(
    body: s.ReplaceRequest, principal: ActivePrincipal, db: DbSession, user_id: UserId
) -> dict[str, Any]:
    """ADM-012: «Заменить участника» во всех активных проектах (dry run и подтверждение)."""
    return await replace.replace_everywhere(
        db, principal, user_id, body.replacement_user_id,
        dry_run=body.dry_run, project_ids=body.project_ids,
    )  # fmt: skip
