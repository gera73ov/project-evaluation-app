"""CORE-024: копирование ветки из другого проекта (FR-PRJ-03, BR-ROLE-06): источник — проект, где
пользователь сейчас участник; превышение лимита — 409 ``NODES_LIMIT`` и ничего не скопировано."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.tree import Node
from estimator.services.tree import copy_branch
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import Setup, _setup
from tests.integration.core.test_structure_api import _children, _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PRJ-03")]


async def _target_project(s: Setup, db: AsyncSession) -> tuple[uuid.UUID, Node]:
    """Копия проекта с той же командой, запущенная в оценку; ветка Бэкенда в ней."""
    copied = await s.moderator.post(f"/projects/{s.pid}/copy", json={"name": "Приёмник"})
    pid = uuid.UUID(copied.json()["project"]["id"])
    launched = await s.moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    assert launched.status_code == 200, launched.text
    branch = (
        await db.scalars(
            select(Node)
            .where(
                Node.project_id == pid, Node.discipline_id == s.backend, Node.kind == "discipline"
            )
            .order_by(Node.position)
        )
    ).first()
    return pid, branch


async def _copy(actor: Any, target: Any, source: Any) -> Any:
    return await actor.post(f"/nodes/{target}/copy-from", json={"source_node_id": str(source)})


@pytest.mark.spec("BR-ROLE-06")
async def test_copy_branch(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session)
    source_branch = await s.branch(db_session, s.backend)
    pid, target_branch = await _target_project(s, db_session)
    group = await _leaf(s.backend_expert, s, source_branch.id, "Модуль")
    await _leaf(s.backend_expert, s, group["id"], "Вход", o="8", r="12", p="20", multiplier=2)
    await _leaf(s.backend_expert, s, source_branch.id, "Отчёты", o="1", r="2", p="3")

    copied = await _copy(s.backend_expert, target_branch.id, source_branch.id)
    assert copied.status_code == 201, copied.text
    assert [c["status"] for c in copied.json()["branch_statuses"]] == ["draft"]
    assert await _children(db_session, target_branch.id) == ["Отчёты", "Модуль"]
    module = (
        await db_session.scalars(select(Node).where(Node.project_id == pid, Node.title == "Модуль"))
    ).one()
    [leaf] = (await db_session.scalars(select(Node).where(Node.parent_id == module.id))).all()
    assert (leaf.title, leaf.o, leaf.multiplier) == ("Вход", 8, 2)

    # чужая дисциплина — 403 (своя ветка), другая дисциплина источника — 422
    frontend_source = await s.branch(db_session, s.frontend)
    assert (await _copy(s.frontend_expert, target_branch.id, source_branch.id)).status_code == 403
    assert (await _copy(s.moderator, target_branch.id, frontend_source.id)).status_code == 422

    # лимит узлов: отказ целиком
    before = await db_session.scalar(
        select(func.count()).where(Node.project_id == pid, Node.deleted_at.is_(None))
    )
    monkeypatch.setattr(copy_branch, "NODES_LIMIT", before + 1)
    limited = await _copy(s.backend_expert, target_branch.id, source_branch.id)
    assert (limited.status_code, limited.json()["code"]) == (409, "NODES_LIMIT")
    after = await db_session.scalar(
        select(func.count()).where(Node.project_id == pid, Node.deleted_at.is_(None))
    )
    assert after == before


@pytest.mark.spec("BR-ROLE-06")
async def test_copy_from_excluded_project_is_404(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    source_branch = await s.branch(db_session, s.backend)
    _, target_branch = await _target_project(s, db_session)
    team = await s.moderator.put(
        f"/projects/{s.pid}/members",
        json={
            "members": [
                {"user_id": str(s.moderator.id), "role": "moderator"},
                {
                    "user_id": str(s.frontend_expert.id),
                    "role": "expert",
                    "discipline_id": str(s.frontend),
                },
            ]
        },
    )
    assert team.status_code == 200, team.text
    excluded = await _copy(s.backend_expert, target_branch.id, source_branch.id)
    assert excluded.status_code == 404, excluded.text
