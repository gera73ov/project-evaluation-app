"""Список корзины проекта (SPEC FR-TREE-24, Q-04, GAP-06; 15.2 ``GET /projects/{id}/trash``).

Элемент — пакет удаления: корень (узел, чей родитель не в пакете), число узлов, кто и когда
удалил, когда пакет удалит ночная задача (``purge_at`` = удаление + 30 дней; «будет удалён через
N дн.» клиент показывает за 3 дня). Пакеты веток дисциплин, удалённых из проекта, в корзину не
выводятся: ветку возвращает «Добавить дисциплину». Удалённые документы заказчика (GAP-06)
добавляет :func:`estimator.documents.service.trash_items`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Collection
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeKind
from estimator.db.models.tree import Node
from estimator.db.models.users import User
from estimator.services.common import user_ref

RETENTION = dt.timedelta(days=30)  # Q-04


def _iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def list_trash(
    db: AsyncSession, project_id: uuid.UUID, disciplines: Collection[uuid.UUID] | None
) -> list[dict[str, Any]]:
    """Пакеты корзины, новые сверху; ``disciplines`` — только эти дисциплины (эксперт)."""
    rows = (
        await db.execute(
            select(
                Node.id,
                Node.parent_id,
                Node.kind,
                Node.title,
                Node.position,
                Node.discipline_id,
                Node.deleted_batch_id,
                Node.deleted_at,
                Node.deleted_by,
            ).where(Node.project_id == project_id, Node.deleted_batch_id.is_not(None))
        )
    ).all()
    batches: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for row in rows:
        batches[row.deleted_batch_id].append(row)
    authors = {r.deleted_by for r in rows if r.deleted_by is not None}
    names = {
        uid: (name, str(status))
        for uid, name, status in (
            await db.execute(
                select(User.id, User.full_name, User.status).where(User.id.in_(authors))
            )
        ).all()
    }
    out = []
    for batch_id, members in batches.items():
        ids = {m.id for m in members}
        roots = sorted((m for m in members if m.parent_id not in ids), key=lambda m: m.position)
        root = roots[0]
        if root.kind is not NodeKind.ITEM:
            continue  # ветка дисциплины, удалённой из проекта
        if disciplines is not None and root.discipline_id not in disciplines:
            continue
        author = names.get(root.deleted_by) if root.deleted_by else None
        out.append(
            {
                "batch_id": str(batch_id),
                "kind": "nodes",
                "root_title": root.title,
                "nodes_count": len(members),
                "discipline_id": str(root.discipline_id) if root.discipline_id else None,
                "deleted_at": _iso(root.deleted_at),
                "deleted_by": (
                    user_ref(root.deleted_by, author[0], is_active=author[1] == "active")
                    if author and root.deleted_by
                    else None
                ),
                "purge_at": _iso(root.deleted_at + RETENTION),
                "document": None,
            }
        )
    out.sort(key=lambda item: item["deleted_at"], reverse=True)
    return out
