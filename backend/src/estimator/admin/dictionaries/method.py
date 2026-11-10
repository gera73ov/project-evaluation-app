"""«Пороги и проценты» (ADM-007; SPEC 7.5, GAP-13; openapi.yaml ``/admin/method-settings``).

Значения — ключи ``method.*`` таблицы ``system_settings`` (contracts/settings.schema.json). Ключа
нет в таблице — действует значение по умолчанию из схемы настроек (:data:`DEFAULTS`; тест сверяет
их со схемой). В ответе ключи без префикса ``method.``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.policy import read_settings
from estimator.db.models.settings import SystemSetting
from estimator.security import audit
from estimator.services.common import hours

PREFIX = "method."
LEAF_MAX = Decimal("99999.5")
PM_MAX = Decimal(50)
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


def _validation(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def from_api(body: dict[str, Any]) -> dict[str, Any]:
    """``MethodSettings`` запроса → значения ``method.*`` по contracts/settings.schema.json."""
    leaf: dict[str, int | float] = {}
    for level in ("medium", "detailed"):
        value = Decimal(str(body["large_leaf_hours"][level]))
        if not Decimal(0) < value <= LEAF_MAX or value != value.quantize(Decimal("0.01")):
            raise _validation(f"large_leaf_hours/{level}", "Порог — больше 0 и до 99 999,5 ч")
        leaf[level] = _number(value)
    units = {k: int(body["medium_expected_units"][k]) for k in ("min", "max")}
    if units["min"] > units["max"]:
        raise _validation("medium_expected_units/min", "Минимум не больше максимума")
    pm = Decimal(str(body["pm_percent_default"]))
    if not Decimal(0) <= pm <= PM_MAX or (pm * 2) % 1 != 0:
        raise _validation("pm_percent_default", "% УП — от 0 до 50 с шагом 0,5")
    return {
        "large_leaf_hours": leaf,
        "medium_expected_units": units,
        "pm_percent_default": _number(pm),
        "autoarchive_days": int(body["autoarchive_days"]),
    }


async def save(db: AsyncSession, actor: Principal, body: dict[str, Any]) -> dict[str, Any]:
    """Записать «Пороги и проценты»; аудит ``dict.changed`` «было → стало» (BR-ADM-01).

    % УП по умолчанию действует на новые проекты, пороги подсказок и срок автоархивации — сразу
    (их читают при каждом расчёте и запуске задачи)."""
    before = await current(db)
    values = from_api(body)
    changes = {k: [before.get(k), v] for k, v in values.items() if before.get(k) != v}
    for key, value in values.items():
        if key in changes:
            await db.merge(SystemSetting(key=PREFIX + key, value=value, updated_by=actor.user_id))
    await db.flush()
    if changes:
        await audit.write(
            db, "dict.changed", user_id=actor.user_id, login=actor.login,
            session_id=actor.session_id, object_type="dictionary_item", object_id="method",
            details={"dictionary": "method", "op": "update", "changes": changes},
        )  # fmt: skip
    return to_api(await current(db))
