"""«Состояние системы» (ADM-003; contracts/openapi.yaml «Система», ``GET /system/health``).
Право ``system.health.read`` — суперадминистратор из разрешённой сети."""

from __future__ import annotations

from typing import Any

from estimator.admin import health
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import system_schemas as s
from estimator.auth.mfa_policy import RedisDep
from estimator.config import get_settings
from estimator.db.session import DbSession

router = ApiRouter(tags=["Система"])


@router.get("/system/health", permission="system.health.read", response_model=s.Health)
async def get_health(db: DbSession, redis: RedisDep) -> dict[str, Any]:
    return await health.report(db, redis, get_settings())
