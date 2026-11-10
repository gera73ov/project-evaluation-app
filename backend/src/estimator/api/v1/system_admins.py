"""Суперадминистраторы, администраторы, аудиторы ИБ и сбросы их учёток (ADM-004;
contracts/openapi.yaml «Система», ``/system/admins``, ``/system/users/{id}/reset-password``,
``/reset-totp``). Права ``system.admins.manage`` и ``system.users.reset_credentials`` — со step-up,
кроме просмотра списка (у ``GET /system/admins`` нет ``x-step-up``)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path, Response

from estimator.admin import admins
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas
from estimator.api.v1 import system_schemas as s
from estimator.auth.context import SessionServiceDep
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession

router = ApiRouter(tags=["Система"])
UserId = Annotated[uuid.UUID, Path(alias="id")]


@router.get(
    "/system/admins",
    permission="system.admins.manage",
    step_up=False,
    response_model=s.AdminAccountList,
)
async def list_admins(db: DbSession) -> dict[str, Any]:
    return {"items": await admins.list_admins(db)}


@router.post(
    "/system/admins",
    permission="system.admins.manage",
    status_code=201,
    response_model=admin_schemas.ActivationLink,
)
async def create_admin(
    principal: ActivePrincipal, db: DbSession, body: s.AdminAccountCreate
) -> dict[str, Any]:
    return await admins.create_admin(
        db, principal, login=body.login, email=body.email, full_name=body.full_name,
        role=body.role, ad_object_guid=body.ad_object_guid,
    )  # fmt: skip


@router.patch(
    "/system/admins/{id}", permission="system.admins.manage", response_model=s.AdminAccount
)
async def patch_admin(
    principal: ActivePrincipal,
    db: DbSession,
    sessions: SessionServiceDep,
    user_id: UserId,
    body: s.AdminAccountPatch,
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    return await admins.patch_admin(db, sessions, principal, user_id, changes)


@router.delete("/system/admins/{id}", permission="system.admins.manage", status_code=204)
async def demote_admin(
    principal: ActivePrincipal, db: DbSession, sessions: SessionServiceDep, user_id: UserId
) -> Response:
    await admins.demote_admin(db, sessions, principal, user_id)
    return Response(status_code=204)


@router.post(
    "/system/users/{id}/reset-password",
    permission="system.users.reset_credentials",
    response_model=admin_schemas.ActivationLink,
)
async def reset_password(
    principal: ActivePrincipal, db: DbSession, user_id: UserId
) -> dict[str, Any]:
    return await admins.reset_password(db, principal, user_id)


@router.post(
    "/system/users/{id}/reset-totp", permission="system.users.reset_credentials", status_code=204
)
async def reset_totp(
    principal: ActivePrincipal, db: DbSession, sessions: SessionServiceDep, user_id: UserId
) -> Response:
    await admins.reset_totp(db, sessions, principal, user_id)
    return Response(status_code=204)
