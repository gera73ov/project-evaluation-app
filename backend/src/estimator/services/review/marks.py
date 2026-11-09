"""CORE-019 · отметка «Проверено» и самопроверка (SPEC FR-REV-01, FR-REV-02, FR-REV-04, Q-33,
BR-BR-02; 15.2 ``POST /nodes/{id}/review``).

* Ревьюер дисциплины и модератор ставят и снимают отметку листу или узлу; у узла отметка ставится
  (снимается) на нём и на всех узлах поддерева.
* ``self_review``: ревьюер — автор последнего изменения O/R/P/×N листа. Отметка модератора проекта
  самопроверкой не считается.
* :func:`clear` снимает отметку при правке (BR-BR-02): O/R/P, ×N — с листа и всех предков;
  добавление узла — с родителя и всех предков.

Каждый изменённый узел: ``version++``, ``field_versions.review``, запись ``review`` в истории и
событие ``node.updated`` со своей версией проекта (одна версия — одно событие).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeAction, NodeKind, ProjectRole
from estimator.db.models.projects import ProjectMember
from estimator.db.models.tree import Node, NodeHistory
from estimator.db.uuid7 import uuid7
from estimator.services.common import emit, user_ref
from estimator.services.tree.load import node_event

ESTIMATE_KEYS = ("o", "r", "p", "multiplier")


async def _subtree(db: AsyncSession, root: Node) -> list[Node]:
    """Узел и все живые потомки (сверху вниз)."""
    out = [root]
    frontier = [root.id]
    while frontier:
        children = (
            await db.scalars(
                select(Node)
                .where(Node.parent_id.in_(frontier), Node.deleted_at.is_(None))
                .order_by(Node.position)
            )
        ).all()
        out.extend(children)
        frontier = [c.id for c in children]
    return out


async def ancestors(db: AsyncSession, node: Node) -> list[Node]:
    """Предки узла от родителя к корню."""
    out: list[Node] = []
    parent_id = node.parent_id
    while parent_id is not None:
        parent = await db.get(Node, parent_id)
        if parent is None:  # pragma: no cover — FK
            break
        out.append(parent)
        parent_id = parent.parent_id
    return out


async def _is_moderator(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    stmt = select(
        exists().where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role == ProjectRole.MODERATOR,
        )
    )
    return bool(await db.scalar(stmt))


async def _last_estimate_author(db: AsyncSession, node_id: uuid.UUID) -> uuid.UUID | None:
    """Автор последнего изменения O/R/P/×N листа (по истории узла)."""
    rows = (
        await db.execute(
            select(NodeHistory.user_id, NodeHistory.changes)
            .where(NodeHistory.node_id == node_id)
            .order_by(NodeHistory.node_version.desc(), NodeHistory.created_at.desc())
        )
    ).all()
    for user_id, changes in rows:
        if any(key in changes for key in ESTIMATE_KEYS):
            return user_id
    return None


async def _write(
    db: AsyncSession,
    principal: Principal,
    node: Node,
    *,
    reviewed: bool,
    self_review: bool,
    now: dt.datetime,
) -> None:
    was = node.reviewed_by is not None
    node.reviewed_by = principal.user_id if reviewed else None
    node.reviewed_at = now if reviewed else None
    node.self_review = self_review if reviewed else False
    node.version += 1
    node.field_versions = dict(node.field_versions) | {"review": node.version}
    node.updated_by = principal.user_id
    await db.flush()
    version = await emit(
        db,
        node.project_id,
        "node.updated",
        {
            "node": node_event(node),
            "author": user_ref(principal.user_id, principal.full_name),
            "changed_fields": ["review"],
        },
    )
    changes: dict[str, list[object]] = {"review": [was, reviewed]}
    if reviewed and self_review:
        changes["self_review"] = [False, True]
    db.add(
        NodeHistory(
            id=uuid7(),
            node_id=node.id,
            project_id=node.project_id,
            project_version=version,
            node_version=node.version,
            user_id=principal.user_id,
            action=NodeAction.REVIEW,
            changes=changes,
        )
    )


async def mark(
    db: AsyncSession, principal: Principal, node: Node, reviewed: bool
) -> list[uuid.UUID]:
    """Поставить или снять «Проверено» на узле и его поддереве; изменённые узлы."""
    if node.kind is NodeKind.PHASE:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="«Проверено» ставят листу, узлу или ветке дисциплины",
            errors=[{"field": "/reviewed", "code": "invalid", "message": "Строка фазы"}],
        )
    moderator = await _is_moderator(db, node.project_id, principal.user_id)
    nodes = await _subtree(db, node)
    parents = {n.parent_id for n in nodes}
    now = dt.datetime.now(dt.UTC)
    changed: list[uuid.UUID] = []
    for n in nodes:
        if (n.reviewed_by is not None) == reviewed:
            continue
        is_leaf = n.id not in parents
        own = (
            reviewed
            and is_leaf
            and not moderator
            and await _last_estimate_author(db, n.id) == principal.user_id
        )
        await _write(db, principal, n, reviewed=reviewed, self_review=own, now=now)
        changed.append(n.id)
    return changed


async def clear(db: AsyncSession, principal: Principal, nodes: Iterable[Node]) -> list[uuid.UUID]:
    """Снять «Проверено» с узлов, где оно стоит (BR-BR-02); изменённые узлы."""
    now = dt.datetime.now(dt.UTC)
    changed: list[uuid.UUID] = []
    for n in nodes:
        if n.reviewed_by is None:
            continue
        await _write(db, principal, n, reviewed=False, self_review=False, now=now)
        changed.append(n.id)
    return changed
