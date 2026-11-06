"""Профиль и сессии пользователя (AUTH-010; contracts/openapi.yaml «Вход и профиль», ``/me*``).

Права: ``authenticated`` (полная сессия, ``ActivePrincipal``), отключение TOTP —
``me.totp.disable`` через :func:`~estimator.security.authz.gate` (step-up). ``POST /me/password``
— в :mod:`estimator.api.v1.auth`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from estimator.auth import profile
from estimator.auth.context import SessionServiceDep
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.auth.sessions import clear_session_cookie, set_session_cookie
from estimator.auth.stepup import confirm_enrollment, start_enrollment
from estimator.db.session import DbSession
from estimator.redis_client import get_redis
from estimator.security.authz import gate
from estimator.security.web.csrf import clear_csrf_cookie, set_csrf_cookie

router = APIRouter(tags=["Вход и профиль"])
RedisDep = Annotated[Redis, Depends(get_redis)]
AUTHENTICATED: dict[str, Any] = {"x-permission": "authenticated"}


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, max_length=profile.TIMEZONE_MAX)


class TotpEnable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notify_digest: bool
    notify_questions: bool


@router.get("/me", openapi_extra=AUTHENTICATED)
async def get_me(principal: ActivePrincipal, db: DbSession) -> dict[str, Any]:
    return await profile.me(db, principal)


@router.patch("/me", openapi_extra=AUTHENTICATED)
async def patch_me(body: MePatch, principal: ActivePrincipal, db: DbSession) -> dict[str, Any]:
    await profile.update_me(
        db,
        principal,
        full_name=body.full_name,
        timezone=body.timezone,
        timezone_set="timezone" in body.model_fields_set,
    )
    return await profile.me(db, principal)


@router.get("/me/sessions", openapi_extra=AUTHENTICATED)
async def my_sessions(
    principal: ActivePrincipal, db: DbSession, sessions: SessionServiceDep
) -> dict[str, list[dict[str, Any]]]:
    items = await profile.list_sessions(db, sessions, principal)
    return {
        "items": [
            {
                "id": s.id,
                "current": s.current,
                "user_agent": s.user_agent,
                "ip": s.ip,
                "created_at": s.created_at.isoformat(),
                "last_seen_at": s.last_seen_at.isoformat(),
            }
            for s in items
        ]
    }


@router.delete("/me/sessions", status_code=204, openapi_extra=AUTHENTICATED)
async def end_my_sessions(
    principal: ActivePrincipal,
    db: DbSession,
    sessions: SessionServiceDep,
    session_id: Annotated[str | None, Query(alias="id", max_length=128)] = None,
) -> Response:
    ended_current = await profile.end_sessions(db, sessions, principal, session_id)
    response = Response(status_code=204)
    if ended_current:
        clear_session_cookie(response)
        clear_csrf_cookie(response)
    return response


@router.post("/me/totp", openapi_extra=AUTHENTICATED)
async def enable_totp(
    body: TotpEnable,
    principal: ActivePrincipal,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    sessions: SessionServiceDep,
) -> dict[str, Any]:
    """Шаг 1 (без кода) — секрет и QR; шаг 2 (с кодом) — подтверждение и резервные коды."""
    if body.code is None:
        started = await start_enrollment(db, redis, principal)
        return {"otpauth_uri": started.otpauth_uri, "secret": started.secret}
    rotated = await confirm_enrollment(
        db, redis, sessions, principal, body.code, user_agent=request.headers.get("user-agent")
    )
    set_session_cookie(response, rotated.session_id)
    set_csrf_cookie(response, rotated.record.csrf)
    return {"backup_codes": list(rotated.backup_codes)}


@router.delete(
    "/me/totp",
    status_code=204,
    openapi_extra={"x-permission": "me.totp.disable"},
    dependencies=[gate("me.totp.disable")],
)
async def disable_totp(
    principal: ActivePrincipal, db: DbSession, sessions: SessionServiceDep
) -> Response:
    await profile.disable_totp(db, sessions, principal)
    return Response(status_code=204)


@router.post("/me/backup-codes", openapi_extra=AUTHENTICATED)
async def regenerate_backup_codes(
    principal: ActivePrincipal, db: DbSession
) -> dict[str, list[str]]:
    return {"backup_codes": await profile.regenerate_backup_codes(db, principal)}


@router.get("/me/notification-settings", openapi_extra=AUTHENTICATED)
async def get_notification_settings(principal: ActivePrincipal, db: DbSession) -> dict[str, bool]:
    return await profile.notification_settings(db, principal)


@router.put("/me/notification-settings", openapi_extra=AUTHENTICATED)
async def put_notification_settings(
    body: NotificationSettings, principal: ActivePrincipal, db: DbSession
) -> dict[str, bool]:
    return await profile.set_notification_settings(
        db, principal, notify_digest=body.notify_digest, notify_questions=body.notify_questions
    )
