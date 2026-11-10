"""Схемы ответов и запросов админки администратора (ADM; contracts/openapi.yaml «Администратор»).

Сверяются с контрактом тестом API-004 (tests/contract/test_openapi_implementation.py).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.common.decimal import DecimalString
from estimator.api.v1.core_schemas import NodeType

_COLOR = r"^#[0-9A-Fa-f]{6}$"
#: ``HoursString``: расчётные часы, 2 знака
_HOURS = r"^\d+\.\d{2}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- справочники (ADM-007) --------------------------------------------------------------------


class Phase(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    sort_order: int
    is_cross_cutting: bool
    is_active: bool


class PhaseList(_Strict):
    items: list[Phase]


class Discipline(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    short_name: str = Field(min_length=1, max_length=12)
    color: str = Field(pattern=_COLOR)
    default_profile_id: uuid.UUID | None
    is_active: bool


class DisciplineList(_Strict):
    items: list[Discipline]


class NodeTypeList(_Strict):
    items: list[NodeType]


class Profile(_Strict):
    id: uuid.UUID
    discipline_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    type_chain: list[uuid.UUID] = Field(min_length=1, max_length=8)
    is_active: bool


class ProfileList(_Strict):
    items: list[Profile]


class Ratio(_Strict):
    id: uuid.UUID
    discipline_a_id: uuid.UUID
    disciplines_b: list[uuid.UUID] = Field(min_length=1)
    min_pct: DecimalString
    max_pct: DecimalString
    is_active: bool


class RatioList(_Strict):
    items: list[Ratio]


class Tag(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=50)
    short_name: str = Field(min_length=1, max_length=12)
    color: str = Field(pattern=_COLOR)
    category: Literal["assumption", "constraint", "risk", "tech"]
    is_active: bool


class TagList(_Strict):
    items: list[Tag]


class Currency(_Strict):
    code: str = Field(pattern=r"^[A-Z]{3}$")
    symbol: str = Field(max_length=8)
    is_active: bool


class CurrencyList(_Strict):
    items: list[Currency]


class VatRate(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=50)
    percent: DecimalString | None
    is_default: bool
    is_active: bool


class VatRateList(_Strict):
    items: list[VatRate]


class LossReason(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    is_other: bool
    is_active: bool


class LossReasonList(_Strict):
    items: list[LossReason]


class LargeLeafHours(_Strict):
    medium: str = Field(pattern=_HOURS)
    detailed: str = Field(pattern=_HOURS)


class ExpectedUnits(_Strict):
    min: int = Field(ge=1, le=1000)
    max: int = Field(ge=1, le=1000)


class MethodSettings(_Strict):
    large_leaf_hours: LargeLeafHours
    medium_expected_units: ExpectedUnits
    pm_percent_default: DecimalString
    autoarchive_days: int = Field(ge=0, le=3650)


# --- пользователи (ADM-006) -------------------------------------------------------------------

SystemRoleName = Literal[
    "superadmin", "admin", "moderator", "presale", "presale_head", "security_auditor"
]
GrantableRole = Literal["moderator", "presale", "presale_head"]
#: Проверка вида адреса; доставку проверяет почта
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserRoleOut(_Strict):
    role: SystemRoleName
    source: Literal["manual", "ad_group"]


class User(_Strict):
    id: uuid.UUID
    login: str
    full_name: str
    email: str | None
    source: Literal["local", "ad"]
    system_roles: list[UserRoleOut]
    status: Literal["active", "blocked", "pending_password", "anonymized"]
    block_reason: Literal["manual", "ad_disabled", "ad_group", "ad_missing", "not_matched"] | None
    last_login_at: str | None
    totp_enabled: bool


class UserList(_Strict):
    items: list[User]
    next_cursor: str | None


class UserCreate(_Strict):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]{3,64}$")
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(default=None, max_length=254, pattern=_EMAIL)  # type: ignore[assignment]
    roles: list[GrantableRole]
    ad_object_guid: uuid.UUID | None = None


class UserPatch(_Strict):
    full_name: str = Field(default=None, min_length=1, max_length=200)  # type: ignore[assignment]
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    roles: list[GrantableRole] = Field(default=None)  # type: ignore[assignment]


class ActivationLink(_Strict):
    emailed: bool
    activation_url: str | None
    expires_at: str


class UserCreated(_Strict):
    user: User
    activation: ActivationLink | None


class BlockRequest(_Strict):
    reason: str | None = Field(default=None, max_length=500)
