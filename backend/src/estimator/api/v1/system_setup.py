"""Мастер первичной настройки (ADM-001; contracts/openapi.yaml «Система»,
``GET/POST /system/setup/{step}``). Право ``system.setup`` — суперадминистратор из разрешённой
сети, только до завершения мастера; step-up не нужен (``x-step-up`` нет)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Path, Request

from estimator.admin import setup
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import system_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.security.ratelimit.limiter import client_ip

router = ApiRouter(tags=["Система"])
Step = Annotated[str, Path(max_length=32)]


@router.get("/system/setup/{step}", permission="system.setup", response_model=s.SetupStep)
async def get_setup_step(db: DbSession, step: Step) -> dict[str, Any]:
    return await setup.get_step(db, step)


@router.post("/system/setup/{step}", permission="system.setup", response_model=s.SetupStep)
async def post_setup_step(
    request: Request, principal: ActivePrincipal, db: DbSession, step: Step, body: s.SetupStepWrite
) -> dict[str, Any]:
    return await setup.post_step(
        db, principal, step, body.values, complete=body.complete, ip=client_ip(request)
    )
