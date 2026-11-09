"""Команда проекта (CORE-012; contracts/openapi.yaml ``GET/PUT /projects/{id}/members``,
``POST /projects/{id}/members/{user_id}/replace``).

Права — ``ApiRouter``: ``project.read``, ``team.write``, ``team.replace_member`` (модератор
проекта); бизнес-проверки состава — :mod:`estimator.services.team`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Query

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import ProjectRole
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.services import team

router = ApiRouter(tags=["Проекты"])


async def _load(db: DbSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


@router.get(
    "/projects/{id}/members",
    permission="project.read",
    response_model=s.MemberList,
    response_model_exclude_unset=True,
)
async def get_members(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    return {"items": await team.members_out(db, id)}


@router.put(
    "/projects/{id}/members",
    permission="team.write",
    response_model=s.MemberList,
    response_model_exclude_unset=True,
)
async def put_members(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.MembersPut,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    specs = [
        team.MemberSpec(m.user_id, m.role, m.discipline_id, m.is_reviewer) for m in body.members
    ]
    await team.put_members(db, principal, project, specs)
    await db.flush()
    return {"items": await team.members_out(db, id)}


@router.post(
    "/projects/{id}/members/{user_id}/replace",
    permission="team.replace_member",
    response_model=s.MemberList,
    response_model_exclude_unset=True,
)
async def replace_member(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    user_id: uuid.UUID,
    body: s.MemberReplace,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    await team.replace_member(db, principal, project, user_id, body.replacement_user_id)
    await db.flush()
    return {"items": await team.members_out(db, id)}


@router.get(
    "/projects/{id}/member-candidates",
    permission="team.write",
    response_model=s.MemberCandidates,
    response_model_exclude_unset=True,
)
async def get_member_candidates(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
    q: str = Query(min_length=2, max_length=100),
    role: ProjectRole | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """CR-005: поиск людей для «+ добавить» и «Заменить» в команде."""
    return {"items": await team.candidates(db, q, role, limit)}
