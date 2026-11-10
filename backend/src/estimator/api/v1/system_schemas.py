"""Схемы раздела «Система» суперадминистратора (ADM-001…004; contracts/openapi.yaml «Система»).

Сверяются с контрактом тестом API-004 (tests/contract/test_openapi_implementation.py).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.v1 import core_schemas as core
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


# --- журнал аудита (SEC-015) ------------------------------------------------------------------


class AuditEntry(_Strict):
    id: int
    ts: dt.datetime
    event_type: str
    category: str
    result: Literal["success", "failure", "denied"]
    user_id: uuid.UUID | None
    login: str | None
    ip: str | None
    user_agent: str | None
    object_type: str | None
    object_id: str | None
    details: dict[str, Any]


class AuditPage(_Strict):
    items: list[AuditEntry]
    next_cursor: str | None


class AuditExport(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: dt.datetime = Field(alias="from")
    to: dt.datetime
    user_id: uuid.UUID | None = None
    event_type: str | None = Field(default=None, max_length=200)
    result: Literal["success", "failure", "denied"] | None = None


# --- AD: проверки, сопоставление ролей (AUTH-015, CR-009) ---------------------------------------


class AdTestConnection(_Strict):
    values: dict[str, Any] | None = None


class AdTestLogin(_Strict):
    values: dict[str, Any] | None = None
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128, repr=False)


class AdTestUser(_Strict):
    full_name: str
    email: str | None
    disabled: bool
    groups: list[str]
    roles: list[Literal["superadmin", "admin", "moderator", "presale", "presale_head",
                        "security_auditor"]]  # fmt: skip
    in_access_group: bool


class AdTestResult(_Strict):
    ok: bool
    elapsed_ms: int
    detail: str | None = None
    user: AdTestUser | None = None


class RoleMappingValues(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role_mapping: dict[str, Any] = Field(alias="auth.ad.role_mapping")


class RoleMappingPreviewRequest(_Strict):
    values: RoleMappingValues


class RoleMappingItem(_Strict):
    user: core.UserRef
    login: str
    removed: list[Literal["moderator", "presale"]]
    added: list[Literal["moderator", "presale"]]


class RoleMappingPreview(_Strict):
    items: list[RoleMappingItem]


# --- поиск в AD (AUTH-017) ----------------------------------------------------------------------


class AdSearchItem(_Strict):
    object_guid: uuid.UUID
    login: str
    full_name: str
    email: str | None
    department: str | None
    in_access_group: bool
    user_id: uuid.UUID | None


class AdSearchList(_Strict):
    items: list[AdSearchItem]


class ProjectAdCreate(_Strict):
    object_guid: uuid.UUID
    discipline_id: uuid.UUID
    is_reviewer: bool = False
