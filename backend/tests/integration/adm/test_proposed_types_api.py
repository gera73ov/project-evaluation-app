"""ADM-009: предложенные типы — список, «Добавить в словарь», «Объединить», «Отклонить»
(FR-TREE-03, 7.5)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeTypeProposal, SystemRole
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.tree import Node
from tests.integration.core.conftest import Actor, World
from tests.integration.core.test_nodes_api import _create, _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-03"), pytest.mark.spec("7.5")]


async def _decisions(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log "
            "WHERE event_type = 'dict.proposed_type.decided' ORDER BY id"
        )
    )
    return [r[0] for r in rows.all()]


async def _local(actor: Actor, pid: uuid.UUID, name: str) -> dict[str, Any]:
    response = await actor.post(f"/projects/{pid}/node-types", json={"name": name, "icon": "robot"})
    assert response.status_code == 201, response.text
    return response.json()


async def test_list_merge_accept_reject(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    setup = await _setup(world, db_session)
    branch = await setup.branch(db_session, setup.backend)
    gateway = await _local(setup.backend_expert, setup.pid, "Шлюз")
    bot = await _local(setup.backend_expert, setup.pid, "Бот")
    junk = await _local(setup.backend_expert, setup.pid, "Мусор")
    node = await _create(setup.backend_expert, setup.pid, branch.id, type_id=gateway["id"])
    assert node.status_code == 201, node.text
    node_id = node.json()["node"]["id"]

    listed = await admin.get("/admin/proposed-types")
    assert listed.status_code == 200, listed.text
    by_name = {t["name"]: t for t in listed.json()["items"]}
    assert set(by_name) == {"Шлюз", "Бот", "Мусор"}
    assert by_name["Шлюз"]["nodes_count"] == 1
    assert by_name["Шлюз"]["author"]["id"] == str(setup.backend_expert.id)
    assert by_name["Шлюз"]["project_id"] == str(setup.pid)
    assert by_name["Шлюз"]["project_name"] == "Портал дилеров"

    # «Объединить»: узлы проекта ссылаются на выбранный тип словаря
    target = await db_session.scalar(select(NodeType).where(NodeType.name == "Интеграция"))
    assert target is not None
    merged = await admin.post(
        f"/admin/proposed-types/{gateway['id']}/merge", json={"target_type_id": str(target.id)}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["id"] == str(target.id)
    relinked = await db_session.get(Node, uuid.UUID(node_id), populate_existing=True)
    assert relinked is not None
    assert relinked.type_id == target.id
    project_types = (await setup.backend_expert.get(f"/projects/{setup.pid}/node-types")).json()
    assert "Шлюз" not in {t["name"] for t in project_types["items"]}
    local = await db_session.get(NodeType, uuid.UUID(gateway["id"]), populate_existing=True)
    assert local is not None
    assert (local.proposal_status, local.merged_into_id) == (NodeTypeProposal.MERGED, target.id)

    # «Добавить в словарь»: тип становится общим
    accepted = await admin.post(f"/admin/proposed-types/{bot['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["project_id"] is None
    dictionary = (await admin.get("/admin/node-types")).json()["items"]
    assert "Бот" in {t["name"] for t in dictionary}

    rejected = await admin.post(f"/admin/proposed-types/{junk['id']}/reject")
    assert rejected.status_code == 204
    assert (await admin.get("/admin/proposed-types")).json()["items"] == []
    still_local = (await setup.backend_expert.get(f"/projects/{setup.pid}/node-types")).json()
    assert "Мусор" in {t["name"] for t in still_local["items"]}

    again = await admin.post(f"/admin/proposed-types/{junk['id']}/accept")
    assert (again.status_code, again.json()["code"]) == (409, "INVALID_TRANSITION")
    assert (await admin.post(f"/admin/proposed-types/{uuid.uuid4()}/reject")).status_code == 404

    decisions = await _decisions(db_session)
    assert [d["decision"] for d in decisions] == ["merged", "accepted", "rejected"]
    assert decisions[0]["nodes_relinked"] == 1
    assert decisions[0]["merged_into"] == str(target.id)


async def test_merge_needs_active_dictionary_type(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    setup = await _setup(world, db_session, launch=False)
    first = await _local(setup.moderator, setup.pid, "Первый")
    second = await _local(setup.moderator, setup.pid, "Второй")
    into_local = await admin.post(
        f"/admin/proposed-types/{first['id']}/merge", json={"target_type_id": second["id"]}
    )
    assert (into_local.status_code, into_local.json()["code"]) == (422, "VALIDATION_FAILED")
    # название уже есть в словаре — только объединить
    clash = await _local(setup.moderator, setup.pid, "экран")
    accepted = await admin.post(f"/admin/proposed-types/{clash['id']}/accept")
    assert (accepted.status_code, accepted.json()["code"]) == (409, "INVALID_TRANSITION")
    expert = await world.actor()
    assert (await expert.get("/admin/proposed-types")).status_code == 403
