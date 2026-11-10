"""Системные настройки и тестовое письмо (ADM-002, CR-009; contracts/openapi.yaml «Система»,
``GET/PUT /system/settings/{section}``, ``POST /system/smtp/test``).

Права: чтение — ``system.settings.read``; запись — ``system.settings.write``, раздел ``auth`` —
``system.auth.manage`` (маршрут объявляет оба, нужное право проверяется по разделу); тестовое
письмо — ``system.settings.write`` без step-up (ничего не записывает).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Path, Request

from estimator.admin import settings
from estimator.admin.settings import smtp_test
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import system_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession
from estimator.security.authz import AuthorizerDep
from estimator.security.ratelimit.limiter import client_ip

router = ApiRouter(tags=["Система"])
Section = Annotated[str, Path(max_length=32)]


@router.get(
    "/system/settings/{section}",
    permission="system.settings.read",
    response_model=s.SettingsSection,
)
async def get_settings(db: DbSession, section: Section) -> dict[str, Any]:
    return await settings.read_section(db, section)


@router.put(
    "/system/settings/{section}",
    permission=["system.settings.write", "system.auth.manage"],
    response_model=s.SettingsSection,
)
async def put_settings(
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
    section: Section,
    body: s.SettingsWrite,
) -> dict[str, Any]:
    await authz.check(settings.write_permission(section))
    await settings.apply(db, principal, section, body.values, ip=client_ip(request))
    return await settings.read_section(db, section)


@router.post(
    "/system/smtp/test",
    permission="system.settings.write",
    step_up=False,
    response_model=s.SmtpTestResult,
)
async def smtp_test_send(db: DbSession, body: s.SmtpTest) -> dict[str, Any]:
    return await smtp_test.send(db, body.to, body.values)
