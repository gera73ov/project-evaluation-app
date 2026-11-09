"""CORE-021 · история узла (SPEC FR-TREE-25, 11.5 №3; 15.2 ``GET /nodes/{id}/history``).

Новые записи сверху: «кто, когда, поле, было → стало» из ``node_history``. «Вернуть это значение»
отдельной операции не имеет: клиент отправляет выбранное значение обычным ``PATCH /nodes/{id}``, и
правка проходит весь путь правки — история, снятие «Проверено», сброс «готово» (BR-BR-02).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.tree import NodeHistory
from estimator.db.models.users import User
from estimator.services.common import user_ref


def _iso(entry: NodeHistory) -> str:
    return entry.created_at.isoformat().replace("+00:00", "Z")


async def node_history(
    db: AsyncSession,
    node_id: uuid.UUID,
    *,
    after: dict[str, Any] | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Страница истории (до ``limit`` записей) и позиция следующей страницы."""
    stmt = (
        select(NodeHistory, User.full_name, User.status)
        .outerjoin(User, User.id == NodeHistory.user_id)
        .where(NodeHistory.node_id == node_id)
        .order_by(NodeHistory.node_version.desc(), NodeHistory.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        version, last = int(after["v"]), uuid.UUID(str(after["id"]))
        stmt = stmt.where(
            or_(
                NodeHistory.node_version < version,
                and_(NodeHistory.node_version == version, NodeHistory.id < last),
            )
        )
    rows = (await db.execute(stmt)).all()
    items = [
        {
            "id": str(entry.id),
            "created_at": _iso(entry),
            "user": (
                user_ref(entry.user_id, name, is_active=str(status) == "active")
                if entry.user_id is not None and name is not None
                else None
            ),
            "action": str(entry.action),
            "changes": entry.changes,
            "node_version": entry.node_version,
            "project_version": entry.project_version,
        }
        for entry, name, status in rows[:limit]
    ]
    more = len(rows) > limit
    last_entry = rows[limit - 1][0] if more else None
    position = {"v": last_entry.node_version, "id": str(last_entry.id)} if last_entry else None
    return items, position
