"""Служебный реестр проектов суперадминистратора (ADM-005; SPEC 3.2, CL-09;
contracts/openapi.yaml ``GET /system/projects``). Право ``registry.read``."""

from __future__ import annotations

from typing import Any

from estimator.admin.registry import system
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.db.session import DbSession

router = ApiRouter(tags=["Система"])
SCOPE = "system.projects"


@router.get(
    "/system/projects",
    permission="registry.read",
    response_model=s.RegistryList,
    response_model_exclude_unset=True,
)
async def system_registry(db: DbSession, page: PageParams) -> dict[str, Any]:
    items, nxt = await system.page(db, after=page.position(SCOPE), limit=page.limit)
    return {"items": items, "next_cursor": encode_cursor(SCOPE, nxt) if nxt else None}
