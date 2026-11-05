"""Деньги проекта (DB-005; contracts/db/schema.md 2.3, G-11, SEC-AUTHZ-04).

Модуль импортирует только сервис денег (``estimator.services.money``) и пакет моделей для
метаданных Alembic; остальные модули — нет. Правило проверяет
``tests/unit/db/test_money_imports.py`` (по образцу контракта import-linter) в CI.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.models.projects import project_fk, user_fk


class ProjectMoney(Base):
    """Валюта, курс, НДС и сумма договора проекта; строка создаётся вместе с проектом."""

    __tablename__ = "project_money"
    __table_args__ = (
        CheckConstraint("exchange_rate > 0", name="exchange_rate"),
        CheckConstraint("currency <> 'RUB' OR exchange_rate = 1", name="rub_rate"),
        CheckConstraint("contract_amount >= 0", name="contract_amount"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk(), primary_key=True)
    currency: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey("currencies.code", ondelete="RESTRICT"), server_default=text("'RUB'")
    )
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), server_default=text("1"))
    vat_rate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vat_rates.id", ondelete="RESTRICT"))
    vat_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()")
    )


class ProjectRate(UUIDPrimaryKey, AuditColumns, Base):
    """Ставка дисциплины в ₽/ч; ``discipline_id IS NULL`` — ставка УП (BR-MONEY-02)."""

    __tablename__ = "project_rates"
    __table_args__ = (
        UniqueConstraint("project_id", "discipline_id", postgresql_nulls_not_distinct=True),
        CheckConstraint("rate_rub BETWEEN 0 AND 1000000", name="rate_rub"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    discipline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    rate_rub: Mapped[Decimal] = mapped_column(Numeric(12, 0))


class _TotalsColumns:
    """Часы (E, P80, P90) и деньги без НДС; ``NULL`` — не поместилось или не вычисляется."""

    e: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    p80: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    p90: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    quote_rub: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    quote_cur: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    updated_at: Mapped[dt.datetime]


class ProjectTotals(_TotalsColumns, Base):
    """Кэш итогов для списков (ARCH-03); денежные столбцы — только с ``money.read``."""

    __tablename__ = "project_totals"

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk(), primary_key=True)
    rates_missing: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    project_version: Mapped[int] = mapped_column(BigInteger)


class ProjectTotalsDaily(_TotalsColumns, Base):
    """Итоги проекта на день по ``app.timezone`` — динамика портфеля (GAP-01)."""

    __tablename__ = "project_totals_daily"
    __table_args__ = (PrimaryKeyConstraint("project_id", "date"),)

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    date: Mapped[dt.date] = mapped_column(Date)
