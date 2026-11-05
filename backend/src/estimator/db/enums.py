"""Перечисления схемы БД (contracts/db/schema.md раздел 7, правило G-7).

Типы ``ENUM`` создают миграции; модели ссылаются на них с ``create_type=False``. Значения
совпадают со строковыми перечислениями ``contracts/openapi.yaml`` — это проверяет
``tests/unit/db/test_enums.py``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class UserSource(StrEnum):
    LOCAL = "local"
    AD = "ad"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING_PASSWORD = "pending_password"  # noqa: S105 — статус, не пароль
    ANONYMIZED = "anonymized"


class UserBlockReason(StrEnum):
    MANUAL = "manual"
    AD_DISABLED = "ad_disabled"
    AD_GROUP = "ad_group"
    AD_MISSING = "ad_missing"
    NOT_MATCHED = "not_matched"


class SystemRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    PRESALE = "presale"
    PRESALE_HEAD = "presale_head"
    SECURITY_AUDITOR = "security_auditor"


class RoleSource(StrEnum):
    MANUAL = "manual"
    AD_GROUP = "ad_group"


class AuthTokenKind(StrEnum):
    ACTIVATION = "activation"
    PASSWORD_RESET = "password_reset"  # noqa: S105 — вид токена, не пароль


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """Тип PostgreSQL ``ENUM`` для модели: значения — ``value``, тип создаёт миграция."""
    return ENUM(
        enum_cls,
        name=name,
        values_callable=lambda cls: [m.value for m in cls],
        create_type=False,
        validate_strings=True,
    )
