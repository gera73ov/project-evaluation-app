"""Закрытые заметки (CORE-031; contracts/openapi.yaml ``listNotes``, ``createNote``,
``patchNote``).

Права ``notes.read`` / ``notes.write``, TOTP в сессии и статус проекта (D-01) проверяет gate;
объект ``/notes/{id}`` — проект заметки (:func:`note_target`). Логика — в
:mod:`estimator.services.notes`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.discussions import ProjectNote
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.security.authz.deps import register_resolver
from estimator.security.authz.engine import Target
from estimator.services.notes import service

router = ApiRouter(tags=["Проекты"])


async def note_target(db: AsyncSession, note_id: uuid.UUID) -> Target | None:
    """Объект ``/notes/{id}``: проект заметки и его статус."""
    row = (
        await db.execute(
            select(ProjectNote.project_id, ProjectNote.author_id, Project.status)
            .join(Project, Project.id == ProjectNote.project_id)
            .where(ProjectNote.id == note_id)
        )
    ).first()
    if row is None:
        return None
    project_id, author_id, status = row
    return Target(project_id=project_id, project_status=str(status), author_id=author_id)


register_resolver("/notes/{id}", note_target)


@router.get(
    "/projects/{id}/notes",
    permission="notes.read",
    response_model=s.NoteList,
    response_model_exclude_unset=True,
)
async def list_notes(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    db: DbSession,
    node_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    scope = f"notes:{id}:{node_id or ''}"
    items, last = await service.list_notes(
        db, id, node_id=node_id, limit=page.limit, after=page.position(scope)
    )
    return {"items": items, "next_cursor": encode_cursor(scope, last) if last else None}


@router.post(
    "/projects/{id}/notes",
    permission="notes.write",
    status_code=201,
    response_model=s.Note,
    response_model_exclude_unset=True,
)
async def create_note(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NoteCreate,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    return await service.create(db, principal, id, body.node_id, body.body)


@router.patch(
    "/notes/{id}",
    permission="notes.write",
    response_model=s.Note,
    response_model_exclude_unset=True,
)
async def patch_note(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.NotePatch,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    note = await db.get(ProjectNote, id)
    if note is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return await service.edit(db, principal, note, body.body)
