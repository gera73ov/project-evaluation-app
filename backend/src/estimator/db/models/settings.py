"""Настройки суперадминистратора (DB-003; contracts/db/schema.md 2.1 ``system_settings``).

Ключи и схемы значений — ``contracts/settings.schema.json`` (ADM-000). Секрет хранится как
``{"enc": "<base64>", "kid": "<id ключа>"}`` (SEC-CRYPT-02/03), открытого значения в БД нет.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        CheckConstraint(r"key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$'", name="key_format"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()")
    )
