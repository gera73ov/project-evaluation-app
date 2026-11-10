"""Список, создание и правка заметок (CORE-031); см. :mod:`estimator.services.notes`."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.models.discussions import ProjectNote
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.realtime.bus import publish
from estimator.services.discussions import feed
from estimator.services.discussions.addressees import invalid


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clean(body: str) -> str:
    if not body.strip():
        raise invalid("body", "заметка не может быть пустой")
    return body


async def note_out(db: AsyncSession, notes: list[ProjectNote]) -> list[dict[str, Any]]:
    authors = await feed.user_refs(db, {n.author_id for n in notes})
    return [
        {
            "id": n.id,
            "node_id": n.node_id,
            "author": authors[n.author_id],
            "body": n.body,
            "created_at": n.created_at,
            "edited_at": n.edited_at,
        }
        for n in notes
    ]


def _ws(note: dict[str, Any]) -> dict[str, Any]:
    return {
        **note,
        "id": str(note["id"]),
        "node_id": str(note["node_id"]) if note["node_id"] else None,
        "created_at": feed.ts(note["created_at"]),
        "edited_at": feed.ts(note["edited_at"]),
    }


async def _publish(db: AsyncSession, note: ProjectNote, event: str) -> dict[str, Any]:
    await db.flush()
    await db.refresh(note)
    [out] = await note_out(db, [note])
    project = await db.get(Project, note.project_id)
    publish(
        db,
        f"project:{note.project_id}:notes",
        event,
        {"note": _ws(out)},
        project_version=project.version if project else None,
    )
    return out


async def list_notes(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    node_id: uuid.UUID | None,
    limit: int,
    after: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    """Заметки проекта по времени создания; ``node_id`` — только заметки узла."""
    query = select(ProjectNote).where(ProjectNote.project_id == project_id)
    if node_id is not None:
        query = query.where(ProjectNote.node_id == node_id)
    if after is not None:
        at, last_id = dt.datetime.fromisoformat(after["t"]), uuid.UUID(after["id"])
        query = query.where(
            or_(
                ProjectNote.created_at > at,
                and_(ProjectNote.created_at == at, ProjectNote.id > last_id),
            )
        )
    rows = (
        await db.scalars(query.order_by(ProjectNote.created_at, ProjectNote.id).limit(limit + 1))
    ).all()
    page = list(rows[:limit])
    last = None
    if len(rows) > limit and page:
        last = {"t": page[-1].created_at.isoformat(), "id": str(page[-1].id)}
    return await note_out(db, page), last


async def create(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    node_id: uuid.UUID | None,
    body: str,
) -> dict[str, Any]:
    text = _clean(body)
    if node_id is not None:
        node = await db.get(Node, node_id)
        if node is None or node.deleted_at is not None or node.project_id != project_id:
            raise invalid("node_id", "узла нет в проекте")
    note = ProjectNote(
        project_id=project_id,
        node_id=node_id,
        author_id=principal.user_id,
        body=text,
        created_at=_now(),
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(note)
    return await _publish(db, note, "note.created")


async def edit(
    db: AsyncSession, principal: Principal, note: ProjectNote, body: str
) -> dict[str, Any]:
    text = _clean(body)
    if text == note.body:
        [out] = await note_out(db, [note])
        return out
    note.body = text
    note.edited_at = _now()
    note.updated_by = principal.user_id
    return await _publish(db, note, "note.updated")
