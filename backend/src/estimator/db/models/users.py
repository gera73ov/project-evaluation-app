"""Пользователи, роли, сессии, токены (DB-003; contracts/db/schema.md 2.1 и раздел 3)."""

from __future__ import annotations

import datetime as dt
import uuid
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Sequence,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CIDR, CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, CreatedColumns, UUIDPrimaryKey
from estimator.db.enums import (
    AuthTokenKind,
    RoleSource,
    SystemRole,
    UserBlockReason,
    UserSource,
    UserStatus,
    pg_enum,
)

#: Номер «Удалённый пользователь #N» (SEC-PD-03).
ANONYMIZED_NO_SEQ = Sequence("users_anonymized_no_seq", metadata=Base.metadata)


def _user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="RESTRICT")


class User(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(login) BETWEEN 3 AND 64", name="login_length"),
        CheckConstraint("char_length(email) <= 254", name="email_length"),
        CheckConstraint("source = 'ad' OR ad_object_guid IS NULL", name="ad_guid_source"),
        CheckConstraint("source = 'local' OR password_hash IS NULL", name="password_source"),
        CheckConstraint("NOT totp_enabled OR totp_secret_enc IS NOT NULL", name="totp_secret"),
        CheckConstraint("(status = 'blocked') = (block_reason IS NOT NULL)", name="block_reason"),
        CheckConstraint(
            "(status = 'anonymized') = (anonymized_no IS NOT NULL)", name="anonymized_no"
        ),
        Index("users_email_uq", "email", unique=True, postgresql_where=text("email IS NOT NULL")),
    )

    login: Mapped[str] = mapped_column(CITEXT, unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT)
    full_name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str | None] = mapped_column(Text)
    source: Mapped[UserSource] = mapped_column(
        pg_enum(UserSource, "user_source"), server_default=UserSource.LOCAL.value
    )
    ad_object_guid: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[dt.datetime | None]
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), server_default=UserStatus.PENDING_PASSWORD.value
    )
    block_reason: Mapped[UserBlockReason | None] = mapped_column(
        pg_enum(UserBlockReason, "user_block_reason")
    )
    blocked_at: Mapped[dt.datetime | None]
    last_login_at: Mapped[dt.datetime | None]
    notify_digest: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    notify_questions: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_digest_at: Mapped[dt.datetime | None]
    anonymized_no: Mapped[int | None] = mapped_column(Integer, unique=True)


class UserRole(CreatedColumns, Base):
    """Системная роль пользователя; «Пользователь» не хранится."""

    __tablename__ = "user_roles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role"),
        CheckConstraint("source = 'manual' OR role IN ('moderator', 'presale')", name="ad_group"),
        Index("user_roles_role_idx", "role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    role: Mapped[SystemRole] = mapped_column(pg_enum(SystemRole, "system_role"))
    source: Mapped[RoleSource] = mapped_column(
        pg_enum(RoleSource, "role_source"), server_default=RoleSource.MANUAL.value
    )


class PasswordHistory(UUIDPrimaryKey, Base):
    __tablename__ = "password_history"
    __table_args__ = (
        Index("password_history_user_id_created_at_idx", "user_id", text("created_at DESC")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class BackupCode(UUIDPrimaryKey, Base):
    __tablename__ = "backup_codes"
    __table_args__ = (
        Index("backup_codes_unused_idx", "user_id", postgresql_where=text("used_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    code_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    used_at: Mapped[dt.datetime | None]


class KnownDevice(Base):
    """Известное устройство: семейство браузера + подсеть /24 или /64 (SEC-AUTH-06)."""

    __tablename__ = "known_devices"
    __table_args__ = (PrimaryKeyConstraint("user_id", "ua_family", "subnet"),)

    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    ua_family: Mapped[str] = mapped_column(Text)
    subnet: Mapped[IPv4Network | IPv6Network] = mapped_column(CIDR)
    first_seen_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[dt.datetime]


class UserSession(Base):
    """Строка сессии для списка сессий и аудита; источник истины на запросе — Redis."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("sessions_active_idx", "user_id", postgresql_where=text("revoked_at IS NULL")),
        Index("sessions_expires_at_idx", "expires_at"),
    )

    id_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[dt.datetime]
    expires_at: Mapped[dt.datetime]
    ip: Mapped[IPv4Address | IPv6Address] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    mfa_passed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    step_up_until: Mapped[dt.datetime | None]
    revoked_at: Mapped[dt.datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class AuthToken(UUIDPrimaryKey, Base):
    """Одноразовая ссылка активации или сброса пароля: в БД только SHA-256 (SEC-AUTH-03)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        Index(
            "auth_tokens_active_idx",
            "user_id",
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    kind: Mapped[AuthTokenKind] = mapped_column(pg_enum(AuthTokenKind, "auth_token_kind"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    expires_at: Mapped[dt.datetime]
    used_at: Mapped[dt.datetime | None]
    revoked_at: Mapped[dt.datetime | None]
