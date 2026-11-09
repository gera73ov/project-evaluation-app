"""CORE-020 и CR-006: типы узлов проекта — список (словарь + локальные этого проекта), создание
локального типа экспертом или модератором, иконка только из курируемого набора (FR-TREE-03,
GAP-07)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeKind, NodeTypeProposal, ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.tree import Node, ProjectJournal
from estimator.db.uuid7 import uuid7
from estimator.services.tree.local_types import NodeTypeIcon
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project, discipline

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-03")]


def test_icon_set_matches_seed_types() -> None:
    assert len(NodeTypeIcon) == 30
    seed = {"module", "function", "screen", "integration", "report", "entity", "service"}
    assert seed | {"test_suite", "document", "work"} <= {i.value for i in NodeTypeIcon}


async def test_list_and_create(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    other = await create_project(world, moderator)
    url = f"/projects/{pid}/node-types"

    listed = await moderator.get(url)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert {i["project_id"] for i in items} == {None}
    assert "Экран" in {i["name"] for i in items}
    screen = next(i for i in items if i["name"] == "Экран")
    assert screen["norms"][0] == {"label": "простой", "o": "2", "r": "4", "p": "6"}

    created = await moderator.post(url, json={"name": "  Шлюз оплаты ", "icon": "credit_card"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body | {"id": None} == {
        "id": None,
        "name": "Шлюз оплаты",
        "icon": "credit_card",
        "norms": [],
        "is_system": False,
        "is_active": True,
        "project_id": str(pid),
    }
    row = await db_session.get(NodeType, body["id"])
    assert row.proposal_status is NodeTypeProposal.PROPOSED  # «Предложенные типы» администратора
    journal = (
        await db_session.scalars(
            select(ProjectJournal.changes).where(
                ProjectJournal.project_id == pid, ProjectJournal.action == "project.node_type"
            )
        )
    ).one()
    assert journal == {"name": [None, "Шлюз оплаты"], "icon": [None, "credit_card"]}

    mine = {i["name"] for i in (await moderator.get(url)).json()["items"]}
    assert "Шлюз оплаты" in mine
    theirs = {
        i["name"] for i in (await moderator.get(f"/projects/{other}/node-types")).json()["items"]
    }
    assert "Шлюз оплаты" not in theirs  # тип работает только в своём проекте

    for bad in (
        {"name": "Шлюз", "icon": "my_logo"},  # не из набора (GAP-07)
        {"name": "   ", "icon": "bug"},
        {"name": "Две\nстроки", "icon": "bug"},
        {"name": "x" * 51, "icon": "bug"},
    ):
        response = await moderator.post(url, json=bad)
        assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_FAILED"), bad


async def test_expert_rights_and_hidden_types(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    await moderator.post(f"/projects/{pid}/disciplines", json={"discipline_id": str(backend)})
    expert = await world.actor()
    db_session.add(
        ProjectMember(
            project_id=pid, user_id=expert.id, role=ProjectRole.EXPERT, discipline_id=backend
        )
    )
    await db_session.execute(
        update(Project).where(Project.id == pid).values(status=ProjectStatus.ESTIMATION)
    )
    url = f"/projects/{pid}/node-types"
    made = await expert.post(url, json={"name": "Бот", "icon": "robot"})
    assert made.status_code == 201, made.text
    outsider = await world.actor()
    assert (await outsider.get(url)).status_code == 404

    # выключенный тип словаря остаётся в списке, пока на него ссылается узел проекта
    by_name = {
        t.name: t
        for t in (await db_session.scalars(select(NodeType).where(NodeType.project_id.is_(None))))
    }
    screen, report = by_name["Экран"], by_name["Отчёт"]
    screen.is_active = False
    report.is_active = False
    branch = (
        await db_session.scalars(
            select(Node).where(Node.project_id == pid, Node.kind == NodeKind.DISCIPLINE)
        )
    ).first()
    db_session.add(
        Node(
            id=uuid7(),
            project_id=pid,
            parent_id=branch.id,
            kind=NodeKind.ITEM,
            phase_id=branch.phase_id,
            discipline_id=backend,
            type_id=screen.id,
            title="Личный кабинет",
            position="a0",
        )
    )
    # объединённый локальный тип из списка уходит
    merged = (await db_session.scalars(select(NodeType).where(NodeType.name == "Бот"))).one()
    merged.proposal_status = NodeTypeProposal.MERGED
    merged.merged_into_id = report.id
    await db_session.flush()
    items = {i["name"]: i for i in (await expert.get(url)).json()["items"]}
    assert items["Экран"]["is_active"] is False
    assert "Отчёт" not in items
    assert "Бот" not in items

    await db_session.execute(
        update(Project).where(Project.id == pid).values(status=ProjectStatus.COMPLETED)
    )
    closed = await expert.post(url, json={"name": "Карта", "icon": "map"})
    assert (closed.status_code, closed.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")
