"""«Пороги и проценты» (ADM-007; SPEC 7.5, GAP-13; openapi.yaml ``/admin/method-settings``).

Значения — ключи ``method.*`` таблицы ``system_settings`` (contracts/settings.schema.json). Ключа
нет в таблице — действует значение по умолчанию из схемы настроек (:data:`DEFAULTS`; тест сверяет
их со схемой). В ответе ключи без префикса ``method.``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import read_settings
from estimator.services.common import hours

PREFIX = "method."
#: Значения по умолчанию (``default`` в contracts/settings.schema.json)
DEFAULTS: dict[str, Any] = {
    "large_leaf_hours": {"medium": 80, "detailed": 40},
    "medium_expected_units": {"min": 5, "max": 15},
    "pm_percent_default": 18,
    "autoarchive_days": 180,
}


def _merged(raw: Any, default: dict[str, Any]) -> dict[str, Any]:
    out = dict(default)
    if isinstance(raw, dict):
        out.update({k: v for k, v in raw.items() if k in default})
    return out


def to_api(values: dict[str, Any]) -> dict[str, Any]:
    """Значения ``method.*`` (без префикса) → ``MethodSettings`` ответа."""
    leaf = _merged(values.get("large_leaf_hours"), DEFAULTS["large_leaf_hours"])
    units = _merged(values.get("medium_expected_units"), DEFAULTS["medium_expected_units"])
    pm = values.get("pm_percent_default", DEFAULTS["pm_percent_default"])
    return {
        "large_leaf_hours": {k: hours(Decimal(str(v))) for k, v in leaf.items()},
        "medium_expected_units": {k: int(v) for k, v in units.items()},
        "pm_percent_default": Decimal(str(pm)),
        "autoarchive_days": int(values.get("autoarchive_days", DEFAULTS["autoarchive_days"])),
    }


async def current(db: AsyncSession) -> dict[str, Any]:
    """Действующие значения (без префикса), с подстановкой значений по умолчанию."""
    stored = await read_settings(db, *(PREFIX + key for key in DEFAULTS))
    values = dict(DEFAULTS)
    values.update({key.removeprefix(PREFIX): value for key, value in stored.items()})
    return values
