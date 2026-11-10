"""Способ входа и AD в разделе «Система» (AUTH-015, CR-009; contracts/openapi.yaml
``/system/auth/ad/test-connection``, ``/system/auth/ad/test-login``,
``/system/auth/role-mapping/preview``; AUTH-018: ``/system/auth/switch-mode``, ``/resolve``,
``/last``).

Проверки AD ничего не меняют, кроме отметки об успешной проверке (``auth.ad.verification``), поэтому
step-up не нужен; сохранение параметров — ``PUT /system/settings/auth`` (step-up там).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import system_schemas as s
from estimator.auth import ad_settings
from estimator.auth import switch_mode as switch
from estimator.auth.mfa_policy import ActivePrincipal, RedisDep
from estimator.db.session import DbSession
from estimator.security.ratelimit.limiter import client_ip

router = ApiRouter(tags=["Система"])


@router.post(
    "/system/auth/ad/test-connection",
    permission="system.auth.test",
    step_up=False,
    response_model=s.AdTestResult,
)
async def ad_test_connection(
    principal: ActivePrincipal, db: DbSession, body: s.AdTestConnection
) -> dict[str, Any]:
    return await ad_settings.test_connection(db, principal, body.values or {})


@router.post(
    "/system/auth/ad/test-login",
    permission="system.auth.test",
    step_up=False,
    response_model=s.AdTestResult,
)
async def ad_test_login(
    principal: ActivePrincipal, db: DbSession, body: s.AdTestLogin
) -> dict[str, Any]:
    return await ad_settings.test_login(db, principal, body.values or {}, body.login,
                                        body.password)  # fmt: skip


@router.post(
    "/system/auth/role-mapping/preview",
    permission="system.auth.manage",
    step_up=False,
    response_model=s.RoleMappingPreview,
    response_model_exclude_unset=True,
)
async def role_mapping_preview(db: DbSession, body: s.RoleMappingPreviewRequest) -> dict[str, Any]:
    return await ad_settings.preview(db, body.values.role_mapping)


@router.post(
    "/system/auth/switch-mode",
    permission="system.auth.manage",
    response_model=s.SwitchReport,
)
async def switch_mode(
    request: Request, principal: ActivePrincipal, db: DbSession, redis: RedisDep,
    body: s.SwitchModeRequest,
) -> dict[str, Any]:  # fmt: skip
    return await switch.switch(db, redis, principal, body.mode, dry_run=body.dry_run,
                               ip=client_ip(request))  # fmt: skip


@router.post(
    "/system/auth/switch-mode/resolve",
    permission="system.auth.manage",
    response_model=s.SwitchReport,
)
async def switch_mode_resolve(
    principal: ActivePrincipal, db: DbSession, redis: RedisDep, body: s.SwitchResolve
) -> dict[str, Any]:
    decisions = [(d.user_id, d.object_guid) for d in body.decisions]
    return await switch.resolve(db, redis, principal, decisions)


@router.get(
    "/system/auth/switch-mode/last",
    permission="system.settings.read",
    response_model=s.LastSwitch | None,
    response_model_exclude_unset=True,
)
async def last_switch(db: DbSession, redis: RedisDep) -> dict[str, Any] | None:
    return await switch.last(db, redis)
