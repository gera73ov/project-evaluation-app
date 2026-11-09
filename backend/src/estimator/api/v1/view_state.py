"""Состояние вида проекта (CORE-027; contracts/openapi.yaml «Вход и профиль»,
``GET/PUT /me/view-state/{project_id}``). Право ``project.read`` на проекте из пути."""

from __future__ import annotations

import uuid
from typing import Any

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.services import view_state

router = ApiRouter(tags=["Вход и профиль"])


@router.get("/me/view-state/{project_id}", permission="project.read", response_model=s.ViewState)
async def get_view_state(
    project_id: uuid.UUID, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    return {"state": await view_state.get_state(db, principal.user_id, project_id)}


@router.put("/me/view-state/{project_id}", permission="project.read", response_model=s.ViewState)
async def put_view_state(
    project_id: uuid.UUID, body: s.ViewState, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    state = await view_state.put_state(db, principal.user_id, project_id, body.state)
    return {"state": state}
