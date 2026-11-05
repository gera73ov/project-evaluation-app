"""Декларативная база ORM-моделей (DB-002; contracts/db/schema.md раздел 1).

* Соглашение об именах ограничений и индексов: Alembic и ORM дают одинаковые имена, поэтому
  сравнение моделей со схемой БД (``tests/integration/db/test_schema_matches_models.py``) не видит
  ложных расхождений.
* :class:`UUIDPrimaryKey` — ``id UUID`` версии 7 от приложения, без ``DEFAULT`` в БД (G-2).
* :class:`AuditColumns` — аудиторские поля G-4 (``created_*``, ``updated_*``, ``NULL`` в ``*_by`` —
  «Система»).
* Десятичные значения — только ``Numeric`` с точностью из контракта (G-8), поэтому в карте типов
  нет ``float``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from estimator.db.uuid7 import uuid7

NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """База всех таблиц схемы ``public``; журнал аудита — в схеме ``audit``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 — так требует SQLAlchemy
        uuid.UUID: UUID(as_uuid=True),
        dt.datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


class UUIDPrimaryKey:
    """``id UUID PK``: UUID v7 задаёт приложение (G-2)."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


class CreatedColumns:
    """``created_at``, ``created_by`` (G-4) — для строк, которые не меняются."""

    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AuditColumns(CreatedColumns):
    """Все аудиторские поля G-4; ``updated_at`` обновляет ORM при каждом UPDATE."""

    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
