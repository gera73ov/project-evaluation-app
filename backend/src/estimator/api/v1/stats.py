"""Статистика и «Напомнить не начавшим» (CORE-050…053; contracts/openapi.yaml
``GET /projects/{id}/stats``, ``POST /projects/{id}/remind``).

Права — ``ApiRouter``: ``stats.read`` (деньги — только при ``money.read``), ``team.remind``
(модератор проекта); расчёты — :mod:`estimator.services.stats`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import stats_schemas as ss
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.redis_client import get_redis
from estimator.services import stats as service
from estimator.services.stats import remind as reminder

router = ApiRouter(tags=["Статистика"])
RedisDep = Annotated[Redis, Depends(get_redis)]


async def _load(db: DbSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


@router.get(
    "/projects/{id}/stats",
    permission="stats.read",
    response_model=ss.Stats,
    response_model_exclude_unset=True,
)
async def get_stats(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    access = getattr(request.state, "access", None)
    project = await _load(db, id)
    return await service.project_stats(db, project, with_money=bool(access and access.money))


@router.post("/projects/{id}/remind", permission="team.remind", response_model=ss.RemindResult)
async def remind_not_started(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
    redis: RedisDep,
) -> dict[str, int]:
    return await reminder.remind(db, redis, principal, await _load(db, id))
