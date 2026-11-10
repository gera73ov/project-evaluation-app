"""Способ входа и AD в разделе «Система» (AUTH-015, CR-009; contracts/openapi.yaml
``/system/auth/ad/test-connection``, ``/system/auth/ad/test-login``,
``/system/auth/role-mapping/preview``).

Проверки AD ничего не меняют, кроме отметки об успешной проверке (``auth.ad.verification``), поэтому
step-up не нужен; сохранение параметров — ``PUT /system/settings/auth`` (step-up там).
"""

from __future__ import annotations

from typing import Any

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import system_schemas as s
from estimator.auth import ad_settings
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession

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
