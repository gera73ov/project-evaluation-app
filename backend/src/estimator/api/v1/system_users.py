"""Учётки в разделе «Система» (SEC-014; contracts/openapi.yaml «Система», ``GET /system/users``,
``POST /system/users/{id}/anonymize``). Право ``system.users.anonymize`` — суперадминистратор,
только из разрешённой сети. Анонимизация — со step-up; просмотр списка — без (x-step-up нет).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import Path, Query, Response

from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import schemas
from estimator.auth.context import SessionServiceDep
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.enums import UserStatus
from estimator.db.session import DbSession
from estimator.security.pd import anonymize as pd

router = ApiRouter(tags=["Система"])
SCOPE = "system.users"


@router.get(
    "/system/users",
    permission="system.users.anonymize",
    step_up=False,
    response_model=schemas.SystemUserList,
)
async def list_users(
    db: DbSession,
    page: PageParams,
    status: Annotated[Literal["blocked", "anonymized"], Query()] = "blocked",
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    filt = pd.ListFilter(status=UserStatus(status), q=q)
    rows = await pd.list_users(db, filt, after=page.position(SCOPE), limit=page.limit)
    items = rows[: page.limit]
    more = len(rows) > page.limit
    cursor = None
    if more:
        cursor = encode_cursor(SCOPE, {"k": items[-1]["_k"], "id": str(items[-1]["id"])})
    for item in items:
        item.pop("_k")
    return {"items": items, "next_cursor": cursor}


@router.post("/system/users/{id}/anonymize", permission="system.users.anonymize", status_code=204)
async def anonymize_user(
    principal: ActivePrincipal,
    db: DbSession,
    sessions: SessionServiceDep,
    user_id: Annotated[uuid.UUID, Path(alias="id")],
) -> Response:
    await pd.anonymize(db, sessions, principal, user_id)
    return Response(status_code=204)
