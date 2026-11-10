"""Предложенные типы (ADM-009; SPEC FR-TREE-03, 7.5 «Предложенные типы»; contracts/openapi.yaml
``GET /admin/proposed-types``, ``POST …/{id}/accept``, ``/merge``, ``/reject``).

Локальный тип, созданный в проекте (CORE-020), ждёт решения администратора
(``proposal_status = proposed``):

* «Добавить в словарь» (``accept``) — тип становится типом словаря (``project_id`` снимается) и
  доступен всем проектам; узлы проекта остаются на нём;
* «Объединить с существующим» (``merge``) — узлы проекта перепривязываются к выбранному активному
  типу словаря (каждый узел — событие ``node.updated`` с ``changed_fields = ["type"]``), локальный
  тип помечается ``merged`` и больше не предлагается в проекте;
* «Отклонить» (``reject``) — тип остаётся локальным типом проекта, из списка уходит.

Решение по уже решённому типу — 409 ``INVALID_TRANSITION``. Каждое решение — аудит
``dict.proposed_type.decided``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeTypeProposal
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.models.users import User
from estimator.security import audit
from estimator.services.common import emit, user_ref
from estimator.services.tree.load import node_event
from estimator.services.tree.local_types import type_out


def _iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def list_proposed(db: AsyncSession) -> list[dict[str, Any]]:
    """Ожидающие решения локальные типы: проект, автор, сколько узлов на типе."""
    nodes = (
        select(func.count(Node.id))
        .where(Node.type_id == NodeType.id, Node.deleted_at.is_(None))
        .scalar_subquery()
    )
    rows = await db.execute(
        select(NodeType, Project.name, User.id, User.full_name, nodes)
        .join(Project, Project.id == NodeType.project_id)
        .join(User, User.id == NodeType.created_by)
        .where(NodeType.proposal_status == NodeTypeProposal.PROPOSED)
        .order_by(NodeType.created_at, NodeType.id)
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "icon": t.icon,
            "project_id": t.project_id,
            "project_name": project_name,
            "author": user_ref(author_id, author_name),
            "created_at": _iso(t.created_at),
            "nodes_count": int(count or 0),
        }
        for t, project_name, author_id, author_name, count in rows.all()
    ]


async def _proposed(db: AsyncSession, type_id: uuid.UUID, to: str) -> tuple[NodeType, uuid.UUID]:
    """Предложенный тип под блокировкой и его проект (у предложенного типа он всегда есть)."""
    row = await db.get(NodeType, type_id, with_for_update=True)
    if row is None or (row.project_id is None and row.proposal_status == NodeTypeProposal.NONE):
        raise ApiError("NOT_FOUND")
    if row.proposal_status != NodeTypeProposal.PROPOSED:
        raise ApiError(
            "INVALID_TRANSITION",
            detail="По этому типу уже есть решение",
            **{"from": row.proposal_status.value, "to": to},
        )
    if row.project_id is None:
        raise ApiError("NOT_FOUND")
    return row, row.project_id


async def _audit(
    db: AsyncSession,
    actor: Principal,
    row: NodeType,
    project_id: uuid.UUID,
    decision: str,
    *,
    merged_into: uuid.UUID | None = None,
    relinked: int = 0,
) -> None:
    details: dict[str, Any] = {"decision": decision, "project_id": str(project_id),
                               "nodes_relinked": relinked}  # fmt: skip
    if merged_into is not None:
        details["merged_into"] = str(merged_into)
    await audit.write(
        db, "dict.proposed_type.decided", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="dictionary_item",
        object_id=f"node_types:{row.id}", details=details,
    )  # fmt: skip


async def accept(db: AsyncSession, actor: Principal, type_id: uuid.UUID) -> dict[str, Any]:
    row, project_id = await _proposed(db, type_id, "accepted")
    clash = await db.scalar(
        select(NodeType.id).where(
            NodeType.project_id.is_(None),
            func.lower(NodeType.name) == row.name.lower(),
        )
    )
    if clash is not None:
        raise ApiError(
            "INVALID_TRANSITION",
            detail="В словаре уже есть тип с таким названием: объедините с ним",
            **{"from": "proposed", "to": "accepted"},
        )
    row.project_id = None
    row.proposal_status = NodeTypeProposal.ACCEPTED
    row.updated_by = actor.user_id
    await db.flush()
    await _audit(db, actor, row, project_id, "accepted")
    return type_out(row)


async def merge(
    db: AsyncSession, actor: Principal, type_id: uuid.UUID, target_id: uuid.UUID
) -> dict[str, Any]:
    row, project_id = await _proposed(db, type_id, "merged")
    target = await db.get(NodeType, target_id)
    if target is None or target.project_id is not None or not target.is_active:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Объединять можно только с активным типом словаря",
            errors=[{"field": "/target_type_id", "code": "invalid",
                     "message": "Нужен активный тип словаря"}],
        )  # fmt: skip
    nodes = list(
        await db.scalars(
            select(Node).where(Node.type_id == row.id).order_by(Node.id).with_for_update()
        )
    )
    author = user_ref(actor.user_id, actor.full_name)
    for node in nodes:
        node.type_id = target.id
        node.version += 1
        node.field_versions = dict(node.field_versions or {}) | {"type": node.version}
        node.updated_by = actor.user_id
    row.proposal_status = NodeTypeProposal.MERGED
    row.merged_into_id = target.id
    row.updated_by = actor.user_id
    await db.flush()
    for node in nodes:
        if node.deleted_at is None:
            data = {"node": node_event(node), "author": author, "changed_fields": ["type"]}
            await emit(db, project_id, "node.updated", data)
    await _audit(db, actor, row, project_id, "merged", merged_into=target.id, relinked=len(nodes))
    return type_out(target)


async def reject(db: AsyncSession, actor: Principal, type_id: uuid.UUID) -> None:
    row, project_id = await _proposed(db, type_id, "rejected")
    row.proposal_status = NodeTypeProposal.REJECTED
    row.updated_by = actor.user_id
    await db.flush()
    await _audit(db, actor, row, project_id, "rejected")
