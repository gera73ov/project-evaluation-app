"""Статус ветки дисциплины (CORE-018; contracts/openapi.yaml
``PUT /projects/{id}/branches/{phase}/{discipline}/status``).

Gate пускает по любому из прав ``branch.status.draft_done`` и ``branch.status.not_needed``;
обработчик выбирает право по стрелке перехода и проверяет его на дисциплине ветки (эксперт —
только своя дисциплина, «не нужно» — только модератор).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from estimator.api.common.errors import ApiError
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import BranchStatus, Project
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep, Target
from estimator.services.branches import status as branches

router = ApiRouter(tags=["Дерево"])


@router.put(
    "/projects/{id}/branches/{phase}/{discipline}/status",
    permission=["branch.status.draft_done", "branch.status.not_needed"],
    response_model=s.BranchStatusChange,
)
async def put_branch_status(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    phase: uuid.UUID,
    discipline: uuid.UUID,
    body: s.BranchStatusPut,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    project = await db.get(Project, id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    row = await db.get(BranchStatus, (id, phase, discipline), with_for_update=True)
    if row is None:
        raise ApiError("NOT_FOUND")
    code = branches.permission_for(row.status, body.status)
    await authz.check(
        code,
        Target(
            project_id=project.id,
            project_status=str(project.status),
            disciplines=frozenset({discipline}),
        ),
    )
    return await branches.set_status(db, principal, project, row, body.status)
