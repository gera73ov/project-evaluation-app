"""Удаление поддеревьев в корзину одним пакетом (SPEC FR-TREE-24, BR-TREE-03; 14.2
``nodes.deleted_batch_id``).

Пакет — общий ``deleted_batch_id``, время и автор у всех узлов; одно событие ``node.deleted`` со
своей версией проекта, у каждого узла ``version++`` и запись ``delete`` в истории с этой версией.
Используют «Свернуть в лист» (CORE-016) и удаление узла (CORE-017).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.enums import NodeAction
from estimator.db.models.tree import Node, NodeHistory
from estimator.db.uuid7 import uuid7
from estimator.services.common import emit, user_ref


async def live_subtree(db: AsyncSession, root: Node) -> list[Node]:
    """Узел и все живые потомки, родители раньше детей, соседи по ``position``."""
    out = [root]
    frontier = [root.id]
    while frontier:
        children = (
            await db.scalars(
                select(Node)
                .where(Node.parent_id.in_(frontier), Node.deleted_at.is_(None))
                .order_by(Node.parent_id, Node.position)
            )
        ).all()
        out.extend(children)
        frontier = [c.id for c in children]
    return out


async def trash(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID, roots: Sequence[Node]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Убрать ``roots`` со всеми живыми потомками в корзину; пакет и удалённые узлы."""
    batch_id = uuid7()
    now = dt.datetime.now(dt.UTC)
    nodes: list[Node] = []
    for root in roots:
        nodes.extend(await live_subtree(db, root))
    for n in nodes:
        n.deleted_at = now
        n.deleted_batch_id = batch_id
        n.deleted_by = principal.user_id
        n.version += 1
        n.updated_by = principal.user_id
    await db.flush()
    ids = [n.id for n in nodes]
    version = await emit(
        db,
        project_id,
        "node.deleted",
        {
            "node_ids": [str(i) for i in ids],
            "batch_id": str(batch_id),
            "author": user_ref(principal.user_id, principal.full_name),
        },
    )
    for n in nodes:
        db.add(
            NodeHistory(
                id=uuid7(),
                node_id=n.id,
                project_id=project_id,
                project_version=version,
                node_version=n.version,
                user_id=principal.user_id,
                action=NodeAction.DELETE,
                changes={"deleted_batch_id": [None, str(batch_id)]},
            )
        )
    return batch_id, ids
