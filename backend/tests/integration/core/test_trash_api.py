"""CORE-017: корзина — удаление пакетом, список по ролям, восстановление на прежнее место и в другое
(G-15), восстановление пакета сворачивания (TC-TREE-01), ночная очистка через 30 дней (G-16)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, NodeAction
from estimator.db.models.projects import BranchStatus
from estimator.db.models.tree import Node, NodeHistory
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.trash.tasks import purge
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _children, _force_done, _leaf, _node

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-24")]

S = BranchStatusValue


async def _restore(actor: Any, batch: Any, target: Any = None) -> Any:
    body = {} if target is None else {"target_parent_id": str(target)}
    return await actor.post(f"/trash/{batch}/restore", json=body)


@pytest.mark.spec("BR-BR-02")
@pytest.mark.spec("GAP-06")
async def test_delete_list_and_restore(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(s.backend_expert, s, branch.id, "Отчёты")
    child = await _leaf(s.backend_expert, s, group["id"], "Выгрузка", o="1", r="2", p="3")
    other = await _leaf(s.backend_expert, s, group["id"], "Печать", o="1", r="2", p="3")
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="1", r="2", p="3")

    # удаление одного листа, затем узла: два пакета
    first = await s.backend_expert.delete(f"/nodes/{child['id']}")
    assert first.status_code == 200, first.text
    await _force_done(db_session, s, branch.phase_id, s.backend)
    second = await s.backend_expert.delete(f"/nodes/{group['id']}")
    assert second.status_code == 200, second.text
    body = second.json()
    assert set(body["deleted_ids"]) == {group["id"], other["id"]}
    assert [c["status"] for c in body["branch_statuses"]] == ["draft"]
    assert await _children(db_session, branch.id) == ["Вход"]

    # список: модератор и эксперт ветки видят, эксперт чужой дисциплины — нет
    listed = (await s.moderator.get(f"/projects/{s.pid}/trash")).json()["items"]
    assert [(i["root_title"], i["nodes_count"]) for i in listed] == [
        ("Отчёты", 2),
        ("Выгрузка", 1),
    ]
    item = listed[0]
    deleted_at = dt.datetime.fromisoformat(item["deleted_at"])
    assert dt.datetime.fromisoformat(item["purge_at"]) - deleted_at == dt.timedelta(days=30)
    assert item["deleted_by"]["id"] == str(s.backend_expert.id)
    assert (item["kind"], item["document"], item["discipline_id"]) == (
        "nodes",
        None,
        str(s.backend),
    )
    assert len((await s.backend_expert.get(f"/projects/{s.pid}/trash")).json()["items"]) == 2
    assert (await s.frontend_expert.get(f"/projects/{s.pid}/trash")).json()["items"] == []
    assert (await _restore(s.frontend_expert, item["batch_id"])).status_code == 403

    # восстановление листа: удалённый родитель возвращается вместе с ним, его сосед — нет
    await _force_done(db_session, s, branch.phase_id, s.backend)
    restored = await _restore(s.backend_expert, listed[1]["batch_id"])
    assert restored.status_code == 200, restored.text
    ids = {n["id"] for n in restored.json()["nodes"]}
    assert {group["id"], child["id"], str(branch.id)} <= ids
    assert [c["status"] for c in restored.json()["branch_statuses"]] == ["draft"]
    assert await _children(db_session, group["id"]) == ["Выгрузка"]
    assert (await _node(db_session, other["id"])).deleted_at is not None
    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{s.pid}") if e["event"] == "node.restored"]
    assert {n["id"] for n in event["data"]["nodes"]} == {group["id"], child["id"]}

    # второй пакет: «Отчёты» уже живой, возвращается только «Печать»
    again = await _restore(s.moderator, item["batch_id"])
    assert again.status_code == 200, again.text
    assert await _children(db_session, group["id"]) == ["Печать", "Выгрузка"]  # прежний порядок
    assert (await s.moderator.get(f"/projects/{s.pid}/trash")).json()["items"] == []
    assert (await _restore(s.moderator, item["batch_id"])).status_code == 404

    # строки фазы и ветки в корзину не удаляют
    assert (await s.moderator.delete(f"/nodes/{branch.id}")).status_code == 403


async def test_restore_into_not_needed_branch(world: World, db_session: AsyncSession) -> None:
    """G-15: ветка стала «не нужно» — 409 с выбором места в той же дисциплине."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Отчёты", o="1", r="2", p="3")
    deleted = await s.backend_expert.delete(f"/nodes/{leaf['id']}")
    batch = deleted.json()["batch_id"]
    not_needed = await s.moderator.put(
        f"/projects/{s.pid}/branches/{branch.phase_id}/{s.backend}/status",
        json={"status": "not_needed"},
    )
    assert not_needed.status_code == 200, not_needed.text

    blocked = await _restore(s.moderator, batch)
    assert blocked.status_code == 409, blocked.text
    problem = blocked.json()
    assert (problem["code"], problem["reason"], problem["discipline_id"]) == (
        "RESTORE_TARGET_UNAVAILABLE",
        "branch_not_needed",
        str(s.backend),
    )

    # другое место: узел другой дисциплины — 422, ветка той же дисциплины в другой фазе — 200
    frontend = await s.branch(db_session, s.frontend)
    wrong = await _restore(s.moderator, batch, frontend.id)
    assert wrong.status_code == 422, wrong.text
    same_phase = await _restore(s.moderator, batch, branch.id)
    assert same_phase.status_code == 409  # ветка всё ещё «не нужно»
    other = (
        await db_session.scalars(
            select(Node).where(
                Node.project_id == s.pid,
                Node.discipline_id == s.backend,
                Node.kind == branch.kind,
                Node.phase_id != branch.phase_id,
            )
        )
    ).first()
    moved = await _restore(s.moderator, batch, other.id)
    assert moved.status_code == 200, moved.text
    node = await _node(db_session, leaf["id"])
    assert (node.parent_id, node.phase_id, node.deleted_at) == (other.id, other.phase_id, None)
    status = await db_session.get(BranchStatus, (s.pid, other.phase_id, s.backend))
    assert status.status is S.DRAFT


@pytest.mark.spec("BR-TREE-03")
@pytest.mark.tc("TC-TREE-01")
async def test_restore_collapse_batch(world: World, db_session: AsyncSession) -> None:
    """TC-TREE-01: дети свёрнутого узла восстанавливаются вместе, оценка узла уходит в историю."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(s.backend_expert, s, branch.id, "Модуль")
    await _leaf(s.backend_expert, s, group["id"], "A", o="8", r="12", p="20")
    await _leaf(s.backend_expert, s, group["id"], "B", o="4", r="6", p="8", multiplier=2)
    version = (await _node(db_session, group["id"])).version
    collapsed = await s.backend_expert.post(
        f"/nodes/{group['id']}/collapse", json={"base_version": version}
    )
    batch = collapsed.json()["batch_id"]

    restored = await _restore(s.backend_expert, batch)
    assert restored.status_code == 200, restored.text
    node = {n["id"]: n for n in restored.json()["nodes"]}[group["id"]]
    assert (node["o"], node["r"], node["p"]) == (None, None, None)
    assert await _children(db_session, group["id"]) == ["B", "A"]
    actions = (
        await db_session.scalars(
            select(NodeHistory.action)
            .where(NodeHistory.node_id == uuid.UUID(group["id"]))
            .order_by(NodeHistory.node_version)
        )
    ).all()
    assert actions[-2:] == [NodeAction.COLLAPSE, NodeAction.UPDATE]


@pytest.mark.spec("Q-04")
async def test_purge_after_30_days(world: World, db_session: AsyncSession) -> None:
    """G-16: через 30 дней ночная задача удаляет узел окончательно."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    old = await _leaf(s.backend_expert, s, branch.id, "Старое")
    fresh = await _leaf(s.backend_expert, s, branch.id, "Свежее")
    old_batch = (await s.backend_expert.delete(f"/nodes/{old['id']}")).json()["batch_id"]
    await s.backend_expert.delete(f"/nodes/{fresh['id']}")
    now = dt.datetime.now(dt.UTC)
    await db_session.execute(
        update(Node)
        .where(Node.id == uuid.UUID(old["id"]))
        .values(deleted_at=now - dt.timedelta(days=31))
    )
    await db_session.execute(
        update(Node)
        .where(Node.id == uuid.UUID(fresh["id"]))
        .values(deleted_at=now - dt.timedelta(days=29))
    )

    assert await purge(db_session, now) == 1
    assert await db_session.get(Node, uuid.UUID(old["id"]), populate_existing=True) is None
    titles = [
        i["root_title"] for i in (await s.moderator.get(f"/projects/{s.pid}/trash")).json()["items"]
    ]
    assert titles == ["Свежее"]
    assert (await _restore(s.moderator, old_batch)).status_code == 404
