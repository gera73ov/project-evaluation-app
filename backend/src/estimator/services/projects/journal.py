"""Журнал проекта (``project_journal``, contracts/db/schema.md 3; GAP-02, 11.6 №1).

Пишется в той же транзакции, что и изменение. Денежные ключи — только в записях ``is_money``
(CHECK в БД), десятичные значения — строками (G-9). Чтение журнала — :func:`page` (CORE-032).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.enums import UserStatus
from estimator.db.models.tree import ProjectJournal
from estimator.db.models.users import User
from estimator.services.common import user_ref


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


#: Вид записи в API (contracts/db/schema.md 3 ``project_journal.action``; перечень — CORE-032).
#: Таблица только для INSERT (G-5), поэтому ранние имена переводятся при чтении, а не правкой
#: строк; виды без пары отдаются как записаны.
PUBLIC_ACTIONS = {
    "project.team": "team.changed",
    "project.branch_profile": "branch.profile",
    "project.money.changed": "money.changed",
}


def _iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def page(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    money: bool,
    after: uuid.UUID | None,
    limit: int,
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    """Страница журнала, новые сверху (UUID v7 растёт со временем), и ``id`` последней записи,
    если есть следующая страница.

    Денежные записи (``is_money``) видят только роли с ``money.read`` (12.7, 15.2): у остальных их
    нет в списке. В ответе их «было → стало» лежит в ``money.changes``, а ``changes`` пустой —
    так клиент рисует их денежным цветом.
    """
    stmt = (
        select(ProjectJournal, User.full_name, User.status)
        .outerjoin(User, User.id == ProjectJournal.user_id)
        .where(ProjectJournal.project_id == project_id)
        .order_by(ProjectJournal.id.desc())
        .limit(limit + 1)
    )
    if not money:
        stmt = stmt.where(ProjectJournal.is_money.is_(False))
    if after is not None:
        stmt = stmt.where(ProjectJournal.id < after)
    rows = (await db.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for entry, name, status in rows[:limit]:
        item: dict[str, Any] = {
            "id": str(entry.id),
            "created_at": _iso(entry.created_at),
            "user": (
                user_ref(entry.user_id, name, is_active=status is UserStatus.ACTIVE)
                if entry.user_id is not None and name is not None
                else None
            ),
            "action": PUBLIC_ACTIONS.get(entry.action, entry.action),
            "changes": {} if entry.is_money else entry.changes,
        }
        if entry.is_money:
            item["money"] = {"changes": entry.changes}
        items.append(item)
    more = len(rows) > limit
    return items, (rows[limit - 1][0].id if more else None)
