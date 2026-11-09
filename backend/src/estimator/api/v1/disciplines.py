"""Дисциплины проекта и профиль ветки (CORE-013; contracts/openapi.yaml
``POST /projects/{id}/disciplines``, ``PATCH/DELETE /projects/{id}/disciplines/{discipline_id}``).

``branch.profile.write`` у эксперта ограничен своей дисциплиной (scope ``own_discipline``):
обработчик проверяет право ещё раз на конкретной дисциплине.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Response

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep, Target
from estimator.services.projects import disciplines
from estimator.services.tree.load import load_tree

router = ApiRouter(tags=["Проекты"])


async def _load(db: DbSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


@router.post(
    "/projects/{id}/disciplines",
    permission="project.disciplines.add",
    status_code=201,
    response_model=s.NodesMutation,
    response_model_exclude_unset=True,
)
async def add_discipline(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.DisciplineAdd,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await _load(db, id)
    created = await disciplines.add_discipline(db, principal, project, body.discipline_id)
    await db.flush()
    project = await _load(db, id)
    tree = await load_tree(db, project)
    ids = {str(n.id) for n in created}
    return {
        "nodes": [n for n in tree["nodes"] if n["id"] in ids],
        "project_version": project.version,
        "totals": tree["totals"]["total"],
        "branch_statuses": [
            {
                "phase_id": str(n.phase_id),
                "discipline_id": str(n.discipline_id),
                "status": "not_started",
                "was": "not_started",
            }
            for n in created
        ],
    }


@router.patch(
    "/projects/{id}/disciplines/{discipline_id}",
    permission="branch.profile.write",
    response_model=s.ProjectDisciplineOut,
)
async def patch_discipline_profile(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    discipline_id: uuid.UUID,
    body: s.DisciplineProfilePatch,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await _load(db, id)
    await authz.check(
        "branch.profile.write",
        Target(
            project_id=project.id,
            project_status=str(project.status),
            disciplines=frozenset({discipline_id}),
        ),
    )
    return await disciplines.set_profile(db, principal, project, discipline_id, body.profile_id)


@router.delete(
    "/projects/{id}/disciplines/{discipline_id}",
    permission="project.disciplines.add",
    status_code=204,
)
async def remove_discipline(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    discipline_id: uuid.UUID,
    principal: ActivePrincipal,
    db: DbSession,
) -> Response:
    project = await _load(db, id)
    await disciplines.remove_discipline(db, principal, project, discipline_id)
    return Response(status_code=204)
