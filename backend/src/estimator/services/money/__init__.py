"""Деньги проекта (CORE-030). Единственный модуль, которому разрешён импорт
``estimator.db.models.money`` (G-11, tests/unit/db/test_money_imports.py).

Пока здесь только начальные значения нового проекта (CORE-010): валюта RUB, курс 1, ставка НДС
«по умолчанию» из справочника с копией процента (BR-MONEY-05, C-31). Чтение и правка денег —
задача CORE-030.
"""

from __future__ import annotations

import uuid

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
