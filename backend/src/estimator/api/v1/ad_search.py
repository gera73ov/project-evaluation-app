"""Поиск в каталоге AD (AUTH-017; FR-AUTH-AD-10, Q-16, SEC-AUTHZ-05; ``GET /admin/ad/search``,
``GET /system/auth/ad/search``, ``GET/POST /projects/{id}/ad-search``).

Права — ``ApiRouter``: ``ad.search`` (администратор), ``system.admins.manage`` (суперадминистратор:
мастер настройки и разделы администраторов), ``project.ad_search`` (модератор проекта в режиме
AD). Модератор заводит человека из AD с ролью «Пользователь» и сразу назначает экспертом на
дисциплину (:func:`estimator.services.team.put_members`).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException, Query
from sqlalchemy import select

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as core
from estimator.api.v1 import system_schemas as s
from estimator.auth import ad_search
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import ProjectRole
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.session import DbSession
from estimator.services import team

router = ApiRouter()
Q = Annotated[str, Query(min_length=3, max_length=100)]


@router.get("/admin/ad/search", permission="ad.search", response_model=s.AdSearchList,
            tags=["Администратор"])  # fmt: skip
async def admin_ad_search(db: DbSession, q: Q) -> dict[str, Any]:
    return {"items": await ad_search.search(db, q)}


@router.get("/system/auth/ad/search", permission="system.admins.manage", step_up=False,
            response_model=s.AdSearchList, tags=["Система"])  # fmt: skip
async def system_ad_search(db: DbSession, q: Q) -> dict[str, Any]:
    return {"items": await ad_search.search(db, q)}


@router.get("/projects/{id}/ad-search", permission="project.ad_search",
            response_model=s.AdSearchList, tags=["Проекты"])  # fmt: skip
async def project_ad_search(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
    q: Q,
) -> dict[str, Any]:
    return {"items": await ad_search.search(db, q)}


@router.post("/projects/{id}/ad-search", permission="project.ad_search", status_code=201,
             response_model=core.MemberList, response_model_exclude_unset=True,
             tags=["Проекты"])  # fmt: skip
async def project_ad_create(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ProjectAdCreate,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await db.get(Project, id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    user, _created = await ad_search.ensure_user(
        db, principal, body.object_guid, source="moderator_ad_search", project_id=project.id
    )
    rows = [
        team.MemberSpec(m.user_id, ProjectRole(m.role), m.discipline_id, m.is_reviewer)
        for m in (await db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )).all()
    ]  # fmt: skip
    spec = team.MemberSpec(user.id, ProjectRole.EXPERT, body.discipline_id, body.is_reviewer)
    if spec.key not in {r.key for r in rows}:
        await team.put_members(db, principal, project, [*rows, spec])
        await db.flush()
    return {"items": await team.members_out(db, project.id)}
