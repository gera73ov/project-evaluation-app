"""``GET /projects/{id}/changes?since=`` — догрузка после разрыва (RT-007; FR-TREE-33, ARCH-02).

Право ``tree.read`` проверяет gate ``ApiRouter``; события фильтруются по правам так же, как живые
события WebSocket. Версия старше хранимого ``change_log`` — 410 ``VERSION_TOO_OLD``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from estimator.api.common.errors import ApiError
from estimator.api.common.router import ApiRouter
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.realtime.changes import VersionTooOld, changes_since
from estimator.realtime.ws.hub import ProjectAccess, allowed

router = ApiRouter(tags=["Дерево"])


class ChangesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_version: int
    to_version: int
    events: list[dict[str, Any]]


@router.get("/projects/{id}/changes", permission="tree.read", response_model=ChangesOut)
async def get_changes(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
    since: int = Query(ge=0),
) -> dict[str, Any]:
    project = await db.get(Project, id)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    access = request.state.access
    subscriber = ProjectAccess(
        project_id=id, money=access.money, notes=access.notes, sources=access.sources
    )
    try:
        changes = await changes_since(
            db, id, since, int(project.version), allowed=lambda e: allowed(subscriber, e)
        )
    except VersionTooOld as exc:
        raise ApiError("VERSION_TOO_OLD", current_version=exc.current_version) from None
    return changes.body()
