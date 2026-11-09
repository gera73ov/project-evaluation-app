"""Журнал проекта (``project_journal``, contracts/db/schema.md 3; GAP-02, 11.6 №1).

Пишется в той же транзакции, что и изменение. Денежные ключи — только в записях ``is_money``
(CHECK в БД), десятичные значения — строками (G-9). Чтение журнала — CORE-032.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.models.tree import ProjectJournal


def plain(value: Any) -> Any:
    """Значение для JSONB журнала: десятичные и даты — строками, UUID — строкой."""
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, dt.date | uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def record(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    changes: Mapping[str, tuple[Any, Any]],
    *,
    is_money: bool = False,
) -> None:
    """Добавить запись ``{"<поле>": [было, стало]}``."""
    db.add(
        ProjectJournal(
            project_id=project_id,
            user_id=user_id,
            action=action,
            is_money=is_money,
            changes={k: [plain(old), plain(new)] for k, (old, new) in changes.items()},
        )
    )
