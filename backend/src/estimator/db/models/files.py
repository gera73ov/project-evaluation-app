"""Снимки оценки, файлы выгрузок, документы заказчика (DB-008; contracts/db/schema.md 2.5, 2.6).

Снимок неизменяем (FR-SNAP-02): у роли приложения есть только ``INSERT`` и ``UPDATE`` столбцов
отметки «ошибочный» — права выдаёт миграция ``0009_snapshots_files``.

``snapshots.money_payload`` — деньги (G-11, SEC-AUTHZ-04). Столбец отложен с ``raiseload``:
обычная загрузка снимка его не читает, а обращение к незагруженному атрибуту падает.
Прочитать его можно только явным ``undefer(Snapshot.money_payload)`` — это делает сервис денег
при праве ``money.read``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.enums import ExportStatus, ScanStatus, pg_enum
from estimator.db.models.projects import project_fk, user_fk

_NOW = text("now()")

#: Типы документов заказчика — по сигнатуре файла (SEC-WEB-10)
DOCUMENT_MIME_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
#: 50 МБ на файл (FR-DOC-01)
DOCUMENT_MAX_BYTES = 52_428_800


class Snapshot(UUIDPrimaryKey, Base):
    """Снимок оценки (FR-SNAP-01): часы и настройки в ``payload``, деньги — в ``money_payload``."""

    __tablename__ = "snapshots"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 1", name="name"),
        Index("snapshots_project_id_created_at_idx", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), server_default=text("''"))
    project_version: Mapped[int] = mapped_column(BigInteger)
    created_by: Mapped[uuid.UUID] = mapped_column(user_fk())
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    is_invalid: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    invalidated_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    invalidated_at: Mapped[dt.datetime | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    money_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), deferred=True, deferred_raiseload=True
    )
    payload_sha256: Mapped[bytes] = mapped_column(LargeBinary)


class ExportFile(UUIDPrimaryKey, Base):
    """Файл выгрузки; доступен только автору 24 часа (FR-EXP-05, NFR-REL-06)."""

    __tablename__ = "export_files"
    __table_args__ = (
        Index("export_files_user_id_created_at_idx", "user_id", text("created_at DESC")),
        Index("export_files_expires_at_idx", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    project_id: Mapped[uuid.UUID | None] = mapped_column(project_fk())
    kind: Mapped[str] = mapped_column(Text)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE")
    )
    status: Mapped[ExportStatus] = mapped_column(
        pg_enum(ExportStatus, "export_status"), server_default=ExportStatus.PENDING.value
    )
    file_name: Mapped[str | None] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    expires_at: Mapped[dt.datetime]


class CustomerDocument(UUIDPrimaryKey, AuditColumns, Base):
    """Документ заказчика: файл на томе под своим ключом, ключ — под мастер-ключом.

    SEC-CRYPT-06.
    """

    __tablename__ = "customer_documents"
    __table_args__ = (
        CheckConstraint(
            "mime IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')",
            name="mime",
        ),
        CheckConstraint("size_bytes BETWEEN 1 AND 52428800", name="size_bytes"),
        Index(
            "customer_documents_live_idx", "project_id", postgresql_where=text("deleted_at IS NULL")
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    file_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[uuid.UUID] = mapped_column(unique=True)
    key_enc: Mapped[bytes] = mapped_column(LargeBinary)
    scan_status: Mapped[ScanStatus] = mapped_column(
        pg_enum(ScanStatus, "scan_status"), server_default=ScanStatus.PENDING.value
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(user_fk())
    uploaded_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    deleted_at: Mapped[dt.datetime | None]
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
