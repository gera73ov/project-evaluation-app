"""Снимки и сравнение (CORE-060, CORE-061; contracts/openapi.yaml ``GET/POST
/projects/{id}/snapshots``, ``POST /snapshots/{id}/invalidate``, ``GET /snapshots/{id}/diff``).

Права — ``ApiRouter``: ``snapshot.read``, ``snapshot.create``, ``snapshot.invalidate``,
``snapshot.compare``; для ``/snapshots/{id}`` объект — проект снимка (resolver). Деньги в ответе —
только при ``money.read`` (``request.state.access.money``, SEC-AUTHZ-04).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import snapshot_schemas as ss
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.files import Snapshot
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.security.authz import Target
from estimator.security.authz.deps import register_resolver
from estimator.services import snapshots as service
from estimator.services.money import snapshot as snapshot_money
from estimator.services.snapshots import diff

router = ApiRouter(tags=["Снимки"])
CURRENT = "current"
CURRENT_LABEL = "Текущее состояние"


async def snapshot_target(db: AsyncSession, snapshot_id: uuid.UUID) -> Target | None:
    """Объект ``/snapshots/{id}``: проект снимка и его статус; иначе 404."""
    row = (
        await db.execute(
            select(Project.id, Project.status)
            .join(Snapshot, Snapshot.project_id == Project.id)
            .where(Snapshot.id == snapshot_id)
        )
    ).first()
    return None if row is None else Target(project_id=row[0], project_status=str(row[1]))


register_resolver("/snapshots/{id}", snapshot_target)


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "NOT_FOUND"})


def _with_money(request: Request) -> bool:
    access = getattr(request.state, "access", None)
    return bool(access and access.money)


@router.get(
    "/projects/{id}/snapshots",
    permission="snapshot.read",
    response_model=ss.SnapshotList,
    response_model_exclude_unset=True,
)
async def list_snapshots(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    items = await service.list_snapshots(db, id)
    return {"items": await service.snapshots_out(db, items, with_money=_with_money(request))}


@router.post(
    "/projects/{id}/snapshots",
    permission="snapshot.create",
    status_code=201,
    response_model=ss.SnapshotOut,
    response_model_exclude_unset=True,
)
async def create_snapshot(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: ss.SnapshotCreate,
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    project = await db.get(Project, id, populate_existing=True)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise _not_found()
    created = await service.create(db, principal, project, body.name, body.description)
    [out] = await service.snapshots_out(db, [created], with_money=_with_money(request))
    return out


@router.post(
    "/snapshots/{id}/invalidate",
    permission="snapshot.invalidate",
    response_model=ss.SnapshotOut,
    response_model_exclude_unset=True,
)
async def invalidate_snapshot(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    snapshot = await db.get(Snapshot, id)
    if snapshot is None:  # pragma: no cover — gate уже ответил 404
        raise _not_found()
    await service.invalidate(db, principal, snapshot)
    [out] = await service.snapshots_out(db, [snapshot], with_money=_with_money(request))
    return out


async def _side(db: AsyncSession, snapshot: Snapshot, money: bool) -> diff.Side:
    raw = (
        (await snapshot_money.stored_payloads(db, [snapshot.id])).get(snapshot.id)
        if money
        else None
    )
    return diff.Side(str(snapshot.id), snapshot.name, snapshot.payload, raw)


@router.get(
    "/snapshots/{id}/diff",
    permission="snapshot.compare",
    response_model=ss.Diff,
    response_model_exclude_unset=True,
)
async def snapshot_diff(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    request: Request,
    db: DbSession,
    with_: Annotated[str, Query(alias="with", max_length=64)],
) -> dict[str, Any]:
    base = await db.get(Snapshot, id)
    if base is None:  # pragma: no cover — gate уже ответил 404
        raise _not_found()
    money = _with_money(request)
    if with_ == CURRENT:
        project = await db.get(Project, base.project_id, populate_existing=True)
        if project is None:  # pragma: no cover — снимок держит проект
            raise _not_found()
        raw = await snapshot_money.current_payload(db, project.id) if money else None
        other = diff.Side(None, CURRENT_LABEL, await service.capture(db, project), raw)
    else:
        try:
            other_id = uuid.UUID(with_)
        except ValueError:
            raise _not_found() from None
        found = await db.get(Snapshot, other_id)
        if found is None or found.project_id != base.project_id:
            raise _not_found()
        other = await _side(db, found, money)
    return diff.compare(await _side(db, base, money), other, with_money=money)
