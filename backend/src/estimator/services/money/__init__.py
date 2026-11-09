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
from estimator.db.models.money import ProjectMoney

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
