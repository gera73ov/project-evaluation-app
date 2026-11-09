"""CORE-019: «Проверено» — ставит ревьюер дисциплины или модератор, на узле отмечается всё
поддерево, самопроверка (FR-REV-04, Q-33), снятие при правке по таблице BR-BR-02 (FR-REV-02)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeAction
from estimator.db.models.tree import Node, NodeHistory
from tests.integration.core.conftest import Actor, World
from tests.integration.core.test_nodes_api import Setup, _create, _patch, _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-REV-01")]


async def _with_reviewer(world: World, db: AsyncSession) -> tuple[Setup, Actor]:
    s = await _setup(world, db)
    reviewer = await world.actor()
    team = await s.moderator.put(
        f"/projects/{s.pid}/members",
        json={
            "members": [
                {"user_id": str(s.moderator.id), "role": "moderator"},
                {
                    "user_id": str(s.backend_expert.id),
                    "role": "expert",
                    "discipline_id": str(s.backend),
                },
                {
                    "user_id": str(s.frontend_expert.id),
                    "role": "expert",
                    "discipline_id": str(s.frontend),
                },
                {
                    "user_id": str(reviewer.id),
                    "role": "expert",
                    "discipline_id": str(s.backend),
                    "is_reviewer": True,
                },
            ]
        },
    )
    assert team.status_code == 200, team.text
    return s, reviewer


async def _review(actor: Actor, node_id: Any, reviewed: bool = True) -> Any:
    return await actor.post(f"/nodes/{node_id}/review", json={"reviewed": reviewed})


async def _node(db: AsyncSession, node_id: Any) -> Node:
    return await db.get(Node, uuid.UUID(str(node_id)), populate_existing=True)


@pytest.mark.spec("FR-REV-04")
@pytest.mark.spec("Q-33")
async def test_mark_and_self_review(world: World, db_session: AsyncSession) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    branch = await s.branch(db_session, s.backend)
    own = (await _create(reviewer, s.pid, branch.id, title="Своё", o="1", r="2", p="3")).json()[
        "node"
    ]
    other = (
        await _create(s.backend_expert, s.pid, branch.id, title="Чужое", o="1", r="2", p="3")
    ).json()["node"]

    marked = await _review(reviewer, own["id"])
    assert marked.status_code == 200, marked.text
    [row] = marked.json()["nodes"]
    assert row["self_review"] is True  # ревьюер — автор последней оценки
    assert row["reviewed_by"]["id"] == str(reviewer.id)
    assert row["reviewed_at"]
    assert row["field_versions"]["review"] == row["version"]
    assert (await _review(reviewer, other["id"])).json()["nodes"][0]["self_review"] is False

    # эксперт без признака ревьюера и ревьюер чужой дисциплины — 403
    assert (await _review(s.backend_expert, other["id"], False)).status_code == 403
    frontend = await s.branch(db_session, s.frontend)
    fe_leaf = (await _create(s.frontend_expert, s.pid, frontend.id, title="Экран")).json()["node"]
    assert (await _review(reviewer, fe_leaf["id"])).status_code == 403

    # модератор: своя оценка — не самопроверка
    mine = (
        await _create(s.moderator, s.pid, branch.id, title="Модератор", o="1", r="2", p="3")
    ).json()["node"]
    assert (await _review(s.moderator, mine["id"])).json()["nodes"][0]["self_review"] is False

    # повторная отметка ничего не меняет, снятие — снимает
    again = await _review(reviewer, own["id"])
    assert again.json()["nodes"] == []
    cleared = await _review(reviewer, own["id"], False)
    [row] = cleared.json()["nodes"]
    assert (row["reviewed_by"], row["self_review"]) == (None, False)
    history = (
        await db_session.scalars(
            select(NodeHistory.changes)
            .where(
                NodeHistory.node_id == uuid.UUID(own["id"]),
                NodeHistory.action == NodeAction.REVIEW,
            )
            .order_by(NodeHistory.node_version)
        )
    ).all()
    assert list(history) == [
        {"review": [False, True], "self_review": [False, True]},
        {"review": [True, False]},
    ]
    phase = await db_session.get(Node, branch.parent_id)
    assert (await _review(s.moderator, phase.id)).status_code == 422


async def test_subtree_and_reset(world: World, db_session: AsyncSession) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = (await _create(s.backend_expert, s.pid, branch.id, title="Модуль")).json()["node"]
    a = (
        await _create(s.backend_expert, s.pid, group["id"], title="A", o="1", r="2", p="3")
    ).json()["node"]
    b = (
        await _create(s.backend_expert, s.pid, group["id"], title="B", o="1", r="2", p="3")
    ).json()["node"]

    marked = await _review(reviewer, branch.id)
    assert {n["id"] for n in marked.json()["nodes"]} == {
        str(branch.id),
        group["id"],
        a["id"],
        b["id"],
    }

    # комментарий и название «Проверено» не снимают
    leaf = await _node(db_session, a["id"])
    await _patch(s.backend_expert, a["id"], leaf.version, title="A2")
    assert (await _node(db_session, a["id"])).reviewed_by is not None

    # O/R/P — снимает с листа и всех предков, соседа не трогает (FR-REV-02)
    leaf = await _node(db_session, a["id"])
    changed = await _patch(s.backend_expert, a["id"], leaf.version, o="1.5")
    assert changed.json()["node"]["reviewed_by"] is None
    assert "review" in changed.json()["node"]["field_versions"]
    for node_id in (a["id"], group["id"], branch.id):
        assert (await _node(db_session, node_id)).reviewed_by is None, node_id
    assert (await _node(db_session, b["id"])).reviewed_by is not None

    # добавление — с родителя и предков
    await _review(reviewer, group["id"])
    await _create(s.backend_expert, s.pid, group["id"], title="C")
    assert (await _node(db_session, group["id"])).reviewed_by is None
    assert (await _node(db_session, b["id"])).reviewed_by is not None

    moderator_mark = await _review(s.moderator, group["id"])
    assert moderator_mark.status_code == 200
