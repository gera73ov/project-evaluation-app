"""Проекты: создание и настройки без денег (CORE-010; contracts/openapi.yaml «Проекты»,
``POST /projects``, ``GET/PATCH /projects/{id}``).

Права — ``ApiRouter`` (gate SEC-005): ``project.create`` (системная роль «Модератор»),
``project.read``, ``project.settings.write`` (модератор проекта). ``my_permissions`` в ответе —
подсказка интерфейсу: коды прав пользователя в контексте этого проекта (сервер всё равно
проверяет каждое действие сам).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any

from fastapi import HTTPException, Query, Request
from sqlalchemy import func, select

from estimator.api.common.errors import ApiError
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import ProjectRole, ProjectStatus
from estimator.db.models.projects import Project, SupportSession
from estimator.db.session import DbSession
from estimator.security.authz import Access, Authorizer, AuthorizerDep, Target
from estimator.security.authz.catalog import PSEUDO
from estimator.security.authz.engine import AccessDenied, decide
from estimator.services import projects as service
from estimator.services.projects import copy as project_copy
from estimator.services.projects import home, lifecycle

router = ApiRouter(tags=["Проекты"])

_ACCESS = {"member": "member", "any_project": "presale_head", "support_session": "support"}


async def my_permissions(authz: Authorizer, project: Project) -> list[str]:
    """Права пользователя в проекте (контекст проекта, без глобальных выдач).

    Право с ``totp_gate`` входит в список и без пройденного в сессии TOTP: интерфейс показывает на
    месте денег «🔒 Подтвердите вход кодом» с вводом кода (FR-2FA-05), а не прячет блок. Сами
    денежные эндпоинты по-прежнему отвечают 403 ``TOTP_REQUIRED``.
    """
    catalog = authz.catalog
    codes = tuple(c for c in catalog.permissions if c not in PSEUDO)
    target = Target(project_id=project.id, project_status=str(project.status))
    subject = dataclasses.replace(await authz.subject(project.id, codes), mfa_passed=True)
    found: list[str] = []
    for code in codes:
        try:
            access = decide(catalog, subject, code, target)
        except AccessDenied:
            continue
        if access.context != "global":
            found.append(code)
    return found


async def _load(db: DbSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


async def _support_expires(db: DbSession, user_id: uuid.UUID, project_id: uuid.UUID) -> Any:
    now = dt.datetime.now(dt.UTC)
    return await db.scalar(
        select(func.max(SupportSession.expires_at)).where(
            SupportSession.admin_id == user_id,
            SupportSession.project_id == project_id,
            SupportSession.ended_at.is_(None),
            SupportSession.expires_at > now,
        )
    )


async def _body(db: DbSession, authz: Authorizer, project: Project, access: Access) -> Any:
    expires = None
    if access.context == "support_session":
        expires = await _support_expires(db, authz.principal.user_id, project.id)
    return await service.project_out(
        db,
        project,
        access=_ACCESS.get(access.context, "member"),
        my_permissions=await my_permissions(authz, project),
        support_expires_at=expires,
    )


HOME_SCOPE = "my-projects"


@router.get(
    "/projects",
    permission="project.list_mine",
    response_model=s.ProjectList,
    response_model_exclude_unset=True,
)
async def list_projects(
    principal: ActivePrincipal,
    db: DbSession,
    page: PageParams,
    status: ProjectStatus | None = None,
    role: ProjectRole | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    """«Мои оценки» (FR-HOME-01/02/04): проекты, где пользователь участник."""
    after = page.position(HOME_SCOPE)
    key = None if after is None else after.get("k")
    if after is not None and not (isinstance(key, list) and len(key) == 4):
        raise ApiError("CURSOR_INVALID")
    items, last = await home.my_projects(
        db, principal, home.HomeFilter(status, role, q), after=key, limit=page.limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(HOME_SCOPE, {"k": last}) if last else None,
    }


@router.post(
    "/projects",
    permission="project.create",
    status_code=201,
    response_model=s.ProjectVersioned,
    response_model_exclude_unset=True,
)
async def create_project(
    body: s.ProjectCreate,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await service.create_project(
        db,
        principal,
        service.NewProject(
            name=body.name,
            customer=body.customer,
            description=body.description,
            phase_ids=body.phase_ids,
            detail_level=body.detail_level,
            deadline=body.deadline,
        ),
    )
    await db.flush()
    await db.refresh(project)
    access = await authz.project(project.id, "project.read")
    return {"project": await _body(db, authz, project, access), "project_version": project.version}


@router.get(
    "/projects/{id}",
    permission="project.read",
    response_model=s.ProjectOut,
    response_model_exclude_unset=True,
)
async def get_project(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await _load(db, id)
    return await _body(db, authz, project, request.state.access)


@router.patch(
    "/projects/{id}",
    permission="project.settings.write",
    response_model=s.ProjectVersioned,
    response_model_exclude_unset=True,
)
async def patch_project(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ProjectPatch,
    principal: ActivePrincipal,
    request: Request,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await _load(db, id)
    sent = body.model_fields_set - {"phases", "confirm"}
    values = {field: getattr(body, field) for field in sent}
    for field in (
        "name",
        "customer",
        "description",
        "detail_level",
        "pm_percent",
        "pm_percent_reason",
        "quote_figure",
    ):
        if field in values and values[field] is None:
            del values[field]  # null для обязательных полей — «не менять»
    phases = (
        [service.PhaseChange(p.phase_id, p.is_enabled, p.in_pm_base) for p in body.phases]
        if body.phases
        else None
    )
    version = await service.patch_project(
        db, principal, project, values, phases, confirm=body.confirm
    )
    await db.flush()
    await db.refresh(project)
    access = await authz.project(project.id, "project.read")
    return {"project": await _body(db, authz, project, access), "project_version": version}


@router.post(
    "/projects/{id}/status",
    permission="project.status",
    response_model=s.StatusChangeResult,
)
async def change_status(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.StatusChange,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    version, warnings = await lifecycle.change_status(db, principal, project, body.to, body.reason)
    return {"status": body.to.value, "project_version": version, "warnings": warnings}


@router.post(
    "/projects/{id}/copy",
    permission="project.copy",
    status_code=201,
    response_model=s.ProjectVersioned,
    response_model_exclude_unset=True,
)
async def copy_project(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CopyProject,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    """CORE-023: копия в «Подготовке» с настройками, командой и деревом (FR-PRJ-02)."""
    source = await _load(db, id)
    project, _ = await project_copy.copy_project(
        db, principal, source, body.model_dump(exclude_unset=True).get("name")
    )
    await db.flush()
    await db.refresh(project)
    access = await authz.project(project.id, "project.read")
    return {"project": await _body(db, authz, project, access), "project_version": project.version}
