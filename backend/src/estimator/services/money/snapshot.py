"""CORE-060/061 · деньги снимка (FR-SNAP-01, FR-SNAP-03, SEC-AUTHZ-04, G-11).

``snapshots.money_payload`` пишет и читает только сервис денег: ставки, валюта, курс, НДС на
момент снимка. Остальной снимок (часы, дерево) — :mod:`estimator.services.snapshots`.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.models.files import Snapshot
from estimator.domain import calc
from estimator.services.money.project import money_settings

PM_KEY = "pm"


def settings_payload(settings: calc.MoneySettings) -> dict[str, Any]:
    """Настройки денег как JSON снимка (ключ ставки УП — ``pm``)."""
    return {
        "currency": settings.currency,
        "exchange_rate": format_decimal(settings.exchange_rate),
        "vat_percent": None
        if settings.vat_percent is None
        else format_decimal(settings.vat_percent),
        "rates": {
            (PM_KEY if k is None else k): format_decimal(v) for k, v in settings.rates.items()
        },
    }


def settings_from_payload(raw: Mapping[str, Any]) -> calc.MoneySettings:
    return calc.MoneySettings(
        currency=str(raw["currency"]),
        exchange_rate=Decimal(str(raw["exchange_rate"])),
        vat_percent=None if raw.get("vat_percent") is None else Decimal(str(raw["vat_percent"])),
        rates={
            (None if k == PM_KEY else k): Decimal(str(v)) for k, v in dict(raw["rates"]).items()
        },
    )


async def current_payload(db: AsyncSession, project_id: uuid.UUID) -> dict[str, Any] | None:
    """Деньги проекта сейчас — для нового снимка и для стороны «текущее» сравнения."""
    settings = await money_settings(db, project_id)
    return None if settings is None else settings_payload(settings)


async def stored_payloads(
    db: AsyncSession, snapshot_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """``money_payload`` снимков (вызывающий проверил ``money.read``)."""
    if not snapshot_ids:
        return {}
    rows = await db.execute(
        select(Snapshot.id, Snapshot.money_payload).where(Snapshot.id.in_(snapshot_ids))
    )
    return dict(rows.all())


def quote(result: calc.ProjectResult, raw: Mapping[str, Any] | None) -> calc.FigureMoney | None:
    """«В КП» без НДС по деньгам снимка; ``None`` — ставок не хватает или денег нет."""
    if raw is None:
        return None
    money = calc.calculate_money(result, settings_from_payload(raw))
    return money.quote
