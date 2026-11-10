"""Схемы раздела «Система» суперадминистратора (ADM-001…004; contracts/openapi.yaml «Система»).

Сверяются с контрактом тестом API-004 (tests/contract/test_openapi_implementation.py).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.v1.admin_schemas import _EMAIL

AdminRole = Literal["superadmin", "admin", "security_auditor"]
SetupStepName = Literal["app", "smtp", "auth", "security", "first_admin"]
HealthName = Literal[
    "db", "redis", "smtp", "ldap", "siem", "queue", "backup", "audit_chain", "audit_purge"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- настройки (ADM-002) ----------------------------------------------------------------------


class SettingsSection(_Strict):
    section: str
    values: dict[str, Any]


class SettingsWrite(_Strict):
    values: dict[str, Any]


class SmtpTest(_Strict):
    values: dict[str, Any] | None = None
    to: str = Field(max_length=254, pattern=_EMAIL)


class SmtpTestResult(_Strict):
    ok: bool
    elapsed_ms: int
    detail: str | None


# --- учётки раздела «Система» (ADM-004) ---------------------------------------------------------


class AdminAccount(_Strict):
    id: uuid.UUID
    login: str
    full_name: str
    email: str | None
    roles: list[AdminRole]
    status: Literal["active", "blocked", "pending_password"]
    totp_enabled: bool
    last_login_at: str | None


class AdminAccountList(_Strict):
    items: list[AdminAccount]


class AdminAccountCreate(_Strict):
    login: str = Field(min_length=3, max_length=64)
    email: str = Field(max_length=254, pattern=_EMAIL)
    full_name: str = Field(min_length=1, max_length=200)
    role: AdminRole
    ad_object_guid: uuid.UUID | None = None


class AdminAccountPatch(_Strict):
    roles: list[AdminRole] = Field(default=None)  # type: ignore[assignment]
    status: Literal["active", "blocked"] = Field(default=None)  # type: ignore[assignment]


# --- состояние системы (ADM-003) ----------------------------------------------------------------


class HealthComponent(_Strict):
    name: HealthName
    ok: bool
    detail: str | None
    checked_at: str


class Health(_Strict):
    app_version: str
    schema_version: str
    components: list[HealthComponent]


# --- мастер первичной настройки (ADM-001) -------------------------------------------------------


class SetupStep(_Strict):
    step: SetupStepName
    done: bool
    values: dict[str, Any] = Field(default=None)  # type: ignore[assignment]


class SetupStepWrite(_Strict):
    values: dict[str, Any]
    complete: bool = False
