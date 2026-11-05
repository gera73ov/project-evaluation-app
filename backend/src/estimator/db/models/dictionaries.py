"""Справочники (DB-004; contracts/db/schema.md 2.2).

Удаление логическое через ``is_active`` (G-6), кроме ``work_calendar`` и ``discipline_profiles``.
Значения по умолчанию заводит миграция данных ``0005_seed_dictionaries`` (DB-010).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.enums import CommentTagCategory, NodeTypeProposal, pg_enum

_TRUE = text("true")
_FALSE = text("false")


class Phase(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "phases"
    __table_args__ = (
        Index(
            "phases_one_cross_cutting",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_cross_cutting"),
        ),
        Index("phases_sort_order_idx", "sort_order"),
    )

    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer)
    is_cross_cutting: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class Discipline(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "disciplines"
    __table_args__ = (CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),)

    name: Mapped[str] = mapped_column(String(100), unique=True)
    short_name: Mapped[str] = mapped_column(String(12))
    color: Mapped[str] = mapped_column(String(7))
    default_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "discipline_profiles.id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        )
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class NodeType(UUIDPrimaryKey, AuditColumns, Base):
    """Тип узла; ``project_id`` не NULL — локальный тип проекта (FR-TREE-03)."""

    __tablename__ = "node_types"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(norms) = 'array'", name="norms_array"),
        CheckConstraint("NOT is_system OR is_active", name="system_active"),
        CheckConstraint(
            "(project_id IS NULL) = (proposal_status IN ('none', 'accepted'))",
            name="proposal_scope",
        ),
        CheckConstraint(
            "(proposal_status = 'merged') = (merged_into_id IS NOT NULL)", name="merged"
        ),
        Index(
            "node_types_one_system", text("(true)"), unique=True, postgresql_where=text("is_system")
        ),
        Index(
            "node_types_project_id_idx",
            "project_id",
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        Index(
            "node_types_proposed_idx",
            "proposal_status",
            postgresql_where=text("proposal_status = 'proposed'"),
        ),
    )

    name: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str] = mapped_column(Text)
    norms: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    proposal_status: Mapped[NodeTypeProposal] = mapped_column(
        pg_enum(NodeTypeProposal, "node_type_proposal"),
        server_default=NodeTypeProposal.NONE.value,
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("node_types.id", ondelete="RESTRICT")
    )


class DisciplineProfile(UUIDPrimaryKey, AuditColumns, Base):
    """Профиль дисциплины: цепочка типов для подсказки (FR-TREE-01, FR-TREE-04)."""

    __tablename__ = "discipline_profiles"
    __table_args__ = (
        CheckConstraint("cardinality(type_chain) BETWEEN 1 AND 8", name="type_chain"),
        UniqueConstraint("discipline_id", "name"),
    )

    discipline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(100))
    type_chain: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))


class CommentTag(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "comment_tags"
    __table_args__ = (CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),)

    name: Mapped[str] = mapped_column(String(50))
    short_name: Mapped[str] = mapped_column(String(12))
    color: Mapped[str] = mapped_column(String(7))
    category: Mapped[CommentTagCategory] = mapped_column(
        pg_enum(CommentTagCategory, "comment_tag_category")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class ControlRatio(UUIDPrimaryKey, AuditColumns, Base):
    """«Дисциплина A к сумме дисциплин B, допустимый диапазон» (6.6)."""

    __tablename__ = "control_ratios"
    __table_args__ = (
        CheckConstraint("cardinality(disciplines_b) >= 1", name="disciplines_b"),
        CheckConstraint("0 <= min_pct AND min_pct <= max_pct AND max_pct <= 999.99", name="range"),
    )

    discipline_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    disciplines_b: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    min_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class WorkCalendarDay(AuditColumns, Base):
    """День производственного календаря; нет строк за год — Пн–Пт (Q-43)."""

    __tablename__ = "work_calendar"
    __table_args__ = (
        CheckConstraint("year = EXTRACT(YEAR FROM date)", name="year"),
        Index("work_calendar_year_idx", "year"),
    )

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    is_working: Mapped[bool] = mapped_column(Boolean)
    year: Mapped[int] = mapped_column(SmallInteger)


class LossReason(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "loss_reasons"

    name: Mapped[str] = mapped_column(String(100))
    is_other: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class VatRate(UUIDPrimaryKey, AuditColumns, Base):
    """Ставка НДС; ``percent IS NULL`` — «Без НДС»; ровно одна по умолчанию (C-31)."""

    __tablename__ = "vat_rates"
    __table_args__ = (
        CheckConstraint("percent IS NULL OR percent BETWEEN 0 AND 100", name="percent"),
        CheckConstraint("NOT is_default OR is_active", name="default_active"),
        Index(
            "vat_rates_one_default",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    name: Mapped[str] = mapped_column(String(50))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)


class Currency(AuditColumns, Base):
    """Валюта ISO 4217; RUB неудаляема (7.5)."""

    __tablename__ = "currencies"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z]{3}$'", name="code"),
        CheckConstraint("code <> 'RUB' OR is_active", name="rub_active"),
    )

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)
