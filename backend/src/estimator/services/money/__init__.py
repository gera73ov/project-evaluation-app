"""Деньги проекта (CORE-030). Единственный модуль, которому разрешён импорт
``estimator.db.models.money`` (G-11, tests/unit/db/test_money_imports.py).

Здесь начальные значения нового проекта (CORE-010): валюта RUB, курс 1, ставка НДС «по
умолчанию» из справочника с копией процента (BR-MONEY-05, C-31); перенос при копировании
(CORE-023) и демо-данные (DB-012). Чтение и правка денег — :mod:`.project` (CORE-030), кэш итогов —
:mod:`.totals` (CORE-026).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import VatRate
from estimator.db.models.money import ProjectMoney, ProjectRate
from estimator.db.uuid7 import uuid7

DEFAULT_CURRENCY = "RUB"


async def create_defaults(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Строка ``project_money`` нового проекта со значениями по умолчанию."""
    vat = (
        await db.execute(
            select(VatRate.id, VatRate.percent).where(VatRate.is_default, VatRate.is_active)
        )
    ).first()
    if vat is None:  # pragma: no cover — справочник гарантирует одну ставку по умолчанию
        raise RuntimeError("в справочнике НДС нет ставки по умолчанию (C-31)")
    db.add(
        ProjectMoney(
            project_id=project_id,
            currency=DEFAULT_CURRENCY,
            vat_rate_id=vat.id,
            vat_percent=vat.percent,
            updated_by=user_id,
        )
    )


async def copy_settings(
    db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Валюта, курс, НДС и ставки источника — в копию проекта (FR-PRJ-02, CORE-023)."""
    src = await db.get(ProjectMoney, source_id)
    new = await db.get(ProjectMoney, target_id)
    if src is not None and new is not None:
        new.currency = src.currency
        new.exchange_rate = src.exchange_rate
        new.vat_rate_id = src.vat_rate_id
        new.vat_percent = src.vat_percent
    for rate in (
        await db.scalars(select(ProjectRate).where(ProjectRate.project_id == source_id))
    ).all():
        db.add(
            ProjectRate(
                id=uuid7(),
                project_id=target_id,
                discipline_id=rate.discipline_id,
                rate_rub=rate.rate_rub,
                created_by=user_id,
                updated_by=user_id,
            )
        )


async def set_settings(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    currency: str,
    exchange_rate: Decimal,
    vat_percent: Decimal | None,
    rates: Mapping[uuid.UUID | None, Decimal],
) -> None:
    """Валюта, курс, НДС (ставка справочника с этим процентом) и ставки — для ``seed-demo``."""
    row = await db.get(ProjectMoney, project_id)
    if row is None:  # pragma: no cover — строка создаётся вместе с проектом
        raise RuntimeError("у проекта нет строки project_money")
    vat = (
        await db.execute(
            select(VatRate.id, VatRate.percent).where(
                VatRate.percent.is_(None) if vat_percent is None else VatRate.percent == vat_percent
            )
        )
    ).first()
    if vat is None:  # pragma: no cover — справочник НДС задан миграцией DB-010
        raise RuntimeError(f"в справочнике НДС нет ставки {vat_percent}")
    row.currency, row.exchange_rate = currency, exchange_rate
    row.vat_rate_id, row.vat_percent = vat.id, vat.percent
    row.updated_by = user_id
    for discipline_id, rate in rates.items():
        db.add(
            ProjectRate(
                id=uuid7(),
                project_id=project_id,
                discipline_id=discipline_id,
                rate_rub=rate,
                created_by=user_id,
                updated_by=user_id,
            )
        )
