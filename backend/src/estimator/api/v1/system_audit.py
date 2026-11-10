"""Журнал аудита в разделе «Система» (SEC-015; SEC-AUD-06, Q-27, ``GET /system/audit``).

Право — любое из ``audit.read.all`` (суперадминистратор, аудитор ИБ) и
``audit.read.admin_categories`` (администратор, фильтр категорий). Просмотр первой страницы с
фильтрами пишется в аудит (``audit.viewed``); листание дальше — нет, чтобы журнал не рос от
прокрутки.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import Query, Request

from estimator.api.common.errors import ApiError
from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as core
from estimator.api.v1 import system_schemas as schemas
from estimator.auth.mfa_policy import ActivePrincipal, RedisDep
from estimator.db.session import DbSession
from estimator.exports import engine
from estimator.exports import kinds as _kinds  # noqa: F401 — регистрирует построители
from estimator.security import audit
from estimator.security.audit import view
from estimator.security.ratelimit.limiter import LIMITS, RateLimiter, client_ip

router = ApiRouter(tags=["Система"])
SCOPE = "system.audit"


@router.get(
    "/system/audit",
    permission=["audit.read.all", "audit.read.admin_categories"],
    step_up=False,
    response_model=schemas.AuditPage,
)
async def list_audit(
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
    page: PageParams,
    since: Annotated[dt.datetime | None, Query(alias="from")] = None,
    until: Annotated[dt.datetime | None, Query(alias="to")] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    event_type: Annotated[str | None, Query(max_length=200)] = None,
    result: Annotated[Literal["success", "failure", "denied"] | None, Query()] = None,
) -> dict[str, Any]:
    access = request.state.access
    restricted = view.ADMIN_SCOPE in access.restricted
    filt = view.AuditFilter(
        since=since, until=until, user_id=user_id, event_type=event_type, result=result,
        categories=view.ADMIN_CATEGORIES if restricted else None,
    )  # fmt: skip
    position = page.position(SCOPE)
    before = None
    if position is not None:
        try:
            before = int(position["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("CURSOR_INVALID") from exc
    else:
        await audit.write(
            db, "audit.viewed", user_id=principal.user_id, login=principal.login,
            ip=client_ip(request), session_id=principal.session_id, object_type="audit_log",
            details={"filters": filt.summary()},
        )  # fmt: skip
    rows = await view.list_entries(db, filt, before=before, limit=page.limit)
    items = rows[: page.limit]
    cursor = encode_cursor(SCOPE, {"id": items[-1]["id"]}) if len(rows) > page.limit else None
    return {"items": items, "next_cursor": cursor}


@router.post(
    "/system/audit/export",
    permission="audit.export",
    status_code=202,
    response_model=core.ExportJob,
)
async def export_audit(
    body: schemas.AuditExport,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """CSV журнала за период с фильтрами (SEC-AUD-06, FR-EXP-06); файл строит worker."""
    if body.from_ > body.to:
        raise ApiError("VALIDATION_FAILED", detail="начало периода позже конца")
    await RateLimiter(redis).check(LIMITS["exports"], str(principal.user_id))
    filt = view.AuditFilter(
        since=body.from_, until=body.to, user_id=body.user_id, event_type=body.event_type,
        result=body.result,
    )  # fmt: skip
    row = await engine.start(
        db, principal, "audit_csv", project_id=None, with_money=False, params=filt.to_params()
    )
    return engine.job_out(row)
