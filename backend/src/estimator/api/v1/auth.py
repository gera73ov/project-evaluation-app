"""Эндпоинты входа и паролей (AUTH-004, AUTH-006…008; contracts/openapi.yaml «Вход и профиль»).

Права (``x-permission``) — по контракту: ``public`` (вход, режим входа, «Забыли пароль»),
``token.login_step`` (второй шаг), ``token.activation`` (ссылки), ``session.pre_mfa``
(подключение TOTP, выход), ``authenticated`` (step-up, смена пароля). Ошибки — HTTPException с
``detail={"code": …}``; в RFC 9457 их превращает обработчик API-003.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.asyncio import Redis

from estimator.api.v1 import schemas
from estimator.auth.context import Principal, SessionServiceDep
from estimator.auth.login import AuthError, LoginOutcome, LoginService
from estimator.auth.mfa_policy import (
    ActivePrincipal,
    AnySessionPrincipal,
    PasswordChangePrincipal,
    PreMfaPrincipal,
)
from estimator.auth.passwords import (
    activate,
    change,
    lift_password_change,
    request_reset,
    reset,
)
from estimator.auth.policy import load_auth_mode
from estimator.auth.providers import Credentials
from estimator.auth.sessions import SessionRecord, clear_session_cookie, set_session_cookie
from estimator.auth.stepup import Rotated, confirm_enrollment, start_enrollment, step_up
from estimator.db.session import DbSession
from estimator.redis_client import get_redis
from estimator.security.networks import guard_superadmin_login
from estimator.security.ratelimit.limiter import client_ip, rate_limit
from estimator.security.web.csrf import clear_csrf_cookie, set_csrf_cookie

router = APIRouter(tags=["Вход и профиль"])
RedisDep = Annotated[Redis, Depends(get_redis)]
LOGIN_RATE = [Depends(rate_limit("login_ip"))]
OPTIONS_RATE = [Depends(rate_limit("auth_options"))]


def _perm(code: str | list[str]) -> dict[str, Any]:
    return {"x-permission": code}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Body):
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128, repr=False)


class TotpLoginRequest(_Body):
    login_token: str = Field(max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    backup_code: str | None = Field(default=None, pattern=r"^\d{8}$")

    @model_validator(mode="after")
    def _exactly_one(self) -> TotpLoginRequest:
        if (self.code is None) == (self.backup_code is None):
            raise ValueError("нужно ровно одно из code и backup_code")
        return self


class TotpCode(_Body):
    code: str = Field(pattern=r"^\d{6}$")


class StepUpRequest(_Body):
    code: str = Field(pattern=r"^\d{6}$")
    password: str | None = Field(default=None, min_length=1, max_length=128, repr=False)
    totp_only: bool = False


class TokenPassword(_Body):
    token: str = Field(min_length=43, max_length=128, repr=False)
    password: str = Field(min_length=12, max_length=128, repr=False)


class ForgotRequest(_Body):
    login_or_email: str = Field(min_length=1, max_length=254)


class PasswordChange(_Body):
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


def _start_session(response: Response, session_id: str, record: SessionRecord) -> None:
    set_session_cookie(response, session_id)
    set_csrf_cookie(response, record.csrf)


def _apply(response: Response, outcome: LoginOutcome) -> dict[str, Any]:
    if outcome.session_id is not None and outcome.record is not None:
        _start_session(response, outcome.session_id, outcome.record)
    return outcome.body()


def _rotated(response: Response, rotated: Rotated) -> None:
    _start_session(response, rotated.session_id, rotated.record)


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


async def _superadmin_network(
    principal: Principal, request: Request, db: DbSession, redis: Redis, route: str
) -> None:
    """Сессия суперадминистратора на ``/auth/*`` не из разрешённой сети — 404 (FR-SA-06)."""
    if principal.is_superadmin:
        await guard_superadmin_login(
            db, redis, ip=client_ip(request), route=route, user_id=principal.user_id,
            login=principal.login, session_id=principal.session_id,
        )  # fmt: skip


@router.post(
    "/auth/login",
    openapi_extra=_perm("public"),
    response_model=schemas.LoginResponse,
    response_model_exclude_none=True,
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    sessions: SessionServiceDep,
) -> dict[str, Any]:
    outcome = await LoginService(redis, sessions).password_step(
        db, Credentials(body.login, body.password), ip=client_ip(request), user_agent=_ua(request)
    )
    return _apply(response, outcome)


@router.get(
    "/auth/options",
    openapi_extra=_perm("public"),
    dependencies=OPTIONS_RATE,
    response_model=schemas.AuthOptions,
)
async def auth_options(db: DbSession) -> dict[str, str]:
    mode = await load_auth_mode(db)
    return {"auth_mode": "app" if mode == "local" else "ad"}


@router.post(
    "/auth/totp",
    openapi_extra=_perm("token.login_step"),
    response_model=schemas.LoginResponse,
    response_model_exclude_none=True,
)
async def login_totp(
    body: TotpLoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    sessions: SessionServiceDep,
) -> dict[str, Any]:
    outcome = await LoginService(redis, sessions).totp_step(
        db,
        body.login_token,
        code=body.code,
        backup_code=body.backup_code,
        ip=client_ip(request),
        user_agent=_ua(request),
    )
    return _apply(response, outcome)


@router.post(
    "/auth/logout",
    status_code=204,
    openapi_extra=_perm(["authenticated", "session.pre_mfa", "session.password_change"]),
)
async def logout(
    principal: AnySessionPrincipal, db: DbSession, redis: RedisDep, sessions: SessionServiceDep
) -> Response:
    await LoginService(redis, sessions).logout(db, principal.session_id, principal.user_id)
    response = Response(status_code=204)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    return response


@router.post(
    "/auth/totp/enroll",
    openapi_extra=_perm("session.pre_mfa"),
    response_model=schemas.TotpEnrollStart,
)
async def totp_enroll_start(
    principal: PreMfaPrincipal, request: Request, db: DbSession, redis: RedisDep
) -> dict[str, str]:
    await _superadmin_network(principal, request, db, redis, "/auth/totp/enroll")
    started = await start_enrollment(db, redis, principal)
    return {"otpauth_uri": started.otpauth_uri, "secret": started.secret}


@router.post(
    "/auth/totp/enroll/confirm",
    openapi_extra=_perm("session.pre_mfa"),
    response_model=schemas.BackupCodes,
)
async def totp_enroll_confirm(
    body: TotpCode,
    principal: PreMfaPrincipal,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    sessions: SessionServiceDep,
) -> dict[str, list[str]]:
    await _superadmin_network(principal, request, db, redis, "/auth/totp/enroll/confirm")
    rotated = await confirm_enrollment(
        db, redis, sessions, principal, body.code, user_agent=_ua(request)
    )
    _rotated(response, rotated)
    return {"backup_codes": list(rotated.backup_codes)}


@router.post(
    "/auth/step-up",
    openapi_extra=_perm("authenticated"),
    response_model=schemas.StepUpResponse,
)
async def auth_step_up(
    body: StepUpRequest,
    principal: ActivePrincipal,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    sessions: SessionServiceDep,
) -> dict[str, Any]:
    await _superadmin_network(principal, request, db, redis, "/auth/step-up")
    rotated = await step_up(
        db,
        redis,
        sessions,
        principal,
        code=body.code,
        password=body.password,
        totp_only=body.totp_only,
        ip=client_ip(request),
        user_agent=_ua(request),
    )
    _rotated(response, rotated)
    until = rotated.record.step_up_until
    return {
        "mfa_passed": rotated.record.mfa_passed,
        "step_up_until": datetime.fromtimestamp(until, UTC).isoformat() if until else None,
    }


@router.post(
    "/auth/activate",
    status_code=204,
    openapi_extra=_perm("token.activation"),
    dependencies=LOGIN_RATE,
)
async def auth_activate(body: TokenPassword, db: DbSession) -> Response:
    await activate(db, body.token, body.password)
    return Response(status_code=204)


@router.post(
    "/auth/password/forgot",
    status_code=204,
    openapi_extra=_perm("public"),
    dependencies=LOGIN_RATE,
)
async def password_forgot(body: ForgotRequest, request: Request, db: DbSession) -> Response:
    await request_reset(db, body.login_or_email, ip=client_ip(request))
    return Response(status_code=204)


@router.post(
    "/auth/password/reset",
    status_code=204,
    openapi_extra=_perm("token.activation"),
    dependencies=LOGIN_RATE,
)
async def password_reset(
    body: TokenPassword, db: DbSession, sessions: SessionServiceDep
) -> Response:
    await reset(db, sessions, body.token, body.password)
    return Response(status_code=204)


@router.post(
    "/me/password",
    status_code=204,
    openapi_extra=_perm(["authenticated", "session.password_change"]),
)
async def change_password(
    body: PasswordChange,
    principal: PasswordChangePrincipal,
    request: Request,
    db: DbSession,
    sessions: SessionServiceDep,
) -> Response:
    if body.current_password == body.new_password:
        raise AuthError(422, "PASSWORD_POLICY_VIOLATION", violations=["reused"])
    await change(
        db,
        sessions,
        principal.user_id,
        principal.session_id,
        body.current_password,
        body.new_password,
    )
    response = Response(status_code=204)
    if principal.password_change_required:
        # Истёкший пароль сменён (CR-003): ограничение снимается с новой сессией (FR-SESS-03);
        # если TOTP обязателен и не подключён, сессия остаётся «до подключения» (15 минут)
        _rotated(response, await lift_password_change(db, sessions, principal, _ua(request)))
    return response
