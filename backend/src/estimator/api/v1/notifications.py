"""Уведомления «Мне» (NTF-003; contracts/openapi.yaml «Уведомления», ``GET /notifications``,
``POST /notifications/read``). Право ``authenticated``: только свои уведомления."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Query, Response

from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.notifications import inapp

router = ApiRouter(tags=["Уведомления"])
SCOPE = "notifications"


@router.get("/notifications", permission="authenticated", response_model=s.NotificationList)
async def list_notifications(
    principal: ActivePrincipal,
    db: DbSession,
    page: PageParams,
    unread: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    position = page.position(SCOPE)
    after = uuid.UUID(position["id"]) if position else None
    rows = await inapp.list_notifications(
        db, principal.user_id, unread_only=bool(unread), after_id=after, limit=page.limit
    )
    items = rows[: page.limit]
    more = len(rows) > page.limit
    return {
        "items": [inapp.notification_out(n) for n in items],
        "unread": await inapp.unread_count(db, principal.user_id),
        "next_cursor": encode_cursor(SCOPE, {"id": str(items[-1].id)}) if more else None,
    }


@router.post("/notifications/read", permission="authenticated", status_code=204)
async def mark_read(
    body: s.NotificationsRead, principal: ActivePrincipal, db: DbSession
) -> Response:
    await inapp.mark_read(db, principal.user_id, ids=body.ids or (), all_=body.all)
    return Response(status_code=204)
