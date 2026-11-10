"""Схемы успешных ответов «Вход и профиль» (contracts/openapi.yaml, AUTH-004…010; API-004).

Обработчики возвращают словари, ``response_model`` сверяет их со схемой контракта и описывает
ответ в OpenAPI приложения — так его сравнивает ``tests/contract/test_openapi_implementation``.
Время — строки ISO 8601 (``Timestamp``), идентификатор пользователя — UUID.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.db.enums import SystemRole


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginResponse(_Out):
    """``step`` и (для ``totp``) временный токен; пустые поля в ответ не попадают."""

    step: Literal["done", "totp", "enroll", "password_change"]
    login_token: str = Field(default=None, repr=False)  # type: ignore[assignment]
    expires_in: int = Field(default=None)  # type: ignore[assignment]


class AuthOptions(_Out):
    auth_mode: Literal["app", "ad"]


class TotpEnrollStart(_Out):
    otpauth_uri: str = Field(repr=False)
    secret: str = Field(repr=False)


class BackupCodes(_Out):
    backup_codes: list[str] = Field(repr=False)


class StepUpResponse(_Out):
    mfa_passed: bool
    step_up_until: str | None


class Me(_Out):
    id: uuid.UUID
    login: str
    full_name: str
    email: str | None
    source: Literal["local", "ad"]
    timezone: str | None
    system_roles: list[SystemRole]
    totp_enabled: bool
    totp_required: bool
    mfa_passed: bool
    auth_mode: Literal["app", "ad"]
    session_expires_at: str
    idle_timeout_seconds: int


class SessionOut(_Out):
    id: str
    current: bool
    user_agent: str | None
    ip: str
    created_at: datetime
    last_seen_at: datetime


class SessionList(_Out):
    items: list[SessionOut]


class NotificationSettings(_Out):
    notify_digest: bool
    notify_questions: bool


class SystemUserItem(_Out):
    """Учётка на экране «Анонимизация» (CR-010): без почты и проектных данных."""

    id: uuid.UUID
    login: str
    full_name: str
    roles: list[SystemRole]
    status: Literal["blocked", "anonymized"]
    blocked_at: datetime | None
    last_login_at: datetime | None


class SystemUserList(_Out):
    items: list[SystemUserItem]
    next_cursor: str | None
