"""Журнал аудита (DB-009; contracts/db/schema.md 2.6, раздел 3 ``audit.audit_anchor``).

Только чтение для приложения: вставка — функцией ``audit.append`` (см. миграцию
``0003_audit`` и сервис SEC-004), ``UPDATE``/``DELETE``/``TRUNCATE`` у ``estimator_app`` нет.
"""

from __future__ import annotations

import datetime as dt
import uuid
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Identity,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import Base
from estimator.db.enums import AuditResult

AUDIT_SCHEMA = "audit"

#: Ключ ``pg_advisory_xact_lock`` цепочки: его берут ``audit.append`` и ``audit purge`` (SEC-004).
AUDIT_LOCK_KEY = 0x6175646974


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        PrimaryKeyConstraint("ts", "id"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        Index("audit_log_id_idx", "id"),
        Index("audit_log_ts_idx", "ts"),
        Index("audit_log_user_id_ts_idx", "user_id", "ts"),
        Index("audit_log_event_type_ts_idx", "event_type", "ts"),
        {"schema": AUDIT_SCHEMA, "postgresql_partition_by": "RANGE (ts)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    ts: Mapped[dt.datetime]
    event_type: Mapped[str] = mapped_column(Text)
    result: Mapped[AuditResult] = mapped_column(
        ENUM(
            AuditResult,
            name="audit_result",
            schema=AUDIT_SCHEMA,
            values_callable=lambda cls: [m.value for m in cls],
            create_type=False,
        )
    )
    user_id: Mapped[uuid.UUID | None]
    login: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    session_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary)


class AuditAnchor(Base):
    """Якорь цепочки после ``audit purge`` (SEC-AUD-04); одна строка ``id = 1``."""

    __tablename__ = "audit_anchor"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        {"schema": AUDIT_SCHEMA},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_purged_id: Mapped[int] = mapped_column(BigInteger)
    last_purged_hash: Mapped[bytes] = mapped_column(LargeBinary)
    purged_until: Mapped[dt.datetime]
    purged_at: Mapped[dt.datetime]
