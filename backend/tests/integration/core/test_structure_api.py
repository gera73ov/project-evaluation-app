"""CORE-016: перенос и порядок (FR-TREE-23, 5.1: эксперту — в своей ветке, модератору — по
проекту), разбиение и сворачивание (BR-TREE-02/03, TC-TREE-01), дублирование; строки таблицы
BR-BR-02 для переноса, разбиения и сворачивания (TC-BR-01)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, NodeAction
from estimator.db.models.projects import BranchStatus
from estimator.db.models.tree import Node, NodeHistory
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.tree.structure import split_title
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.test_nodes_api import Setup, _create, _setup
from tests.integration.core.test_review_api import _review, _with_reviewer

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-23")]

S = BranchStatusValue


async def _node(db: AsyncSession, node_id: Any) -> Node:
    return await db.get(Node, uuid.UUID(str(node_id)), populate_existing=True)


async def _leaf(actor: Actor, s: Setup, parent: Any, title: str, **figures: Any) -> dict[str, Any]:
    response = await _create(actor, s.pid, parent, title=title, **figures)
    assert response.status_code == 201, response.text
    return response.json()["node"]


async def _move(
    actor: Actor, db: AsyncSession, node_id: Any, parent: Any, after: Any = None
) -> Any:
    version = (await _node(db, node_id)).version
    body = {"base_version": version, "new_parent_id": str(parent)}
    if after is not None:
        body["after_id"] = str(after)
    return await actor.post(f"/nodes/{node_id}/move", json=body)


async def _children(db: AsyncSession, parent: Any) -> list[str]:
    rows = await db.scalars(
        select(Node.title)
        .where(Node.parent_id == uuid.UUID(str(parent)), Node.deleted_at.is_(None))
        .order_by(Node.position)
    )
    return list(rows.all())


async def _force_done(db: AsyncSession, s: Setup, phase: uuid.UUID, discipline: uuid.UUID) -> None:
    await db.execute(
        update(BranchStatus)
        .where(
            BranchStatus.project_id == s.pid,
            BranchStatus.phase_id == phase,
            BranchStatus.discipline_id == discipline,
        )
        .values(status=S.DONE)
    )


async def _status(db: AsyncSession, s: Setup, phase: uuid.UUID, discipline: uuid.UUID) -> S:
    row = await db.get(BranchStatus, (s.pid, phase, discipline), populate_existing=True)
    return row.status


@pytest.mark.spec("5.1")
@pytest.mark.spec("BR-BR-02")
@pytest.mark.spec("FR-REV-02")
async def test_move_and_reorder(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    be = s.backend_expert
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(be, s, branch.id, "Модуль")
    a = await _leaf(be, s, branch.id, "A", o="1", r="2", p="3")
    b = await _leaf(be, s, branch.id, "B", o="1", r="2", p="3")
    assert await _children(db_session, branch.id) == ["B", "A", "Модуль"]

    # «Вверх/вниз»: порядок меняется, «готово» и «Проверено» остаются
    await _force_done(db_session, s, branch.phase_id, s.backend)
    await _review(reviewer, branch.id)
    up = await _move(be, db_session, a["id"], branch.id)
    assert up.status_code == 200, up.text
    assert up.json()["branch_statuses"] == []
    assert await _children(db_session, branch.id) == ["A", "B", "Модуль"]
    down = await _move(be, db_session, a["id"], branch.id, after=group["id"])
    assert down.status_code == 200, down.text
    assert await _children(db_session, branch.id) == ["B", "Модуль", "A"]
    same = await _move(be, db_session, a["id"], branch.id, after=group["id"])
    assert same.json()["nodes"] == []  # уже на месте: ничего не меняется
    assert await _status(db_session, s, branch.phase_id, s.backend) is S.DONE
    assert (await _node(db_session, branch.id)).reviewed_by is not None

    # смена родителя: «готово» → «черновик», «Проверено» снимается с узла и предков
    moved = await _move(be, db_session, a["id"], group["id"])
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert [c["status"] for c in body["branch_statuses"]] == ["draft"]
    by_id = {n["id"]: n for n in body["nodes"]}
    assert by_id[a["id"]]["parent_id"] == group["id"]
    assert by_id[group["id"]]["e"] == by_id[a["id"]]["e"]  # E нового родителя пересчитана
    for node_id in (a["id"], group["id"], branch.id):
        assert (await _node(db_session, node_id)).reviewed_by is None, node_id
    assert (await _node(db_session, b["id"])).reviewed_by is not None
    [entry] = (
        await db_session.scalars(
            select(NodeHistory.changes).where(
                NodeHistory.node_id == uuid.UUID(a["id"]), NodeHistory.action == NodeAction.MOVE
            )
        )
    ).all()[-1:]
    assert entry["parent"] == [str(branch.id), group["id"]]
    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{s.pid}") if e["event"] == "node.moved"][-1:]
    assert event["data"]["from_parent_id"] == str(branch.id)
    assert event["data"]["node"]["parent_id"] == group["id"]

    # ошибки: внутрь себя, в лист с оценкой, конфликт версии
    inside = await _move(be, db_session, group["id"], a["id"])
    assert inside.status_code == 422, inside.text
    into_leaf = await _move(be, db_session, group["id"], b["id"])
    assert into_leaf.status_code == 422, into_leaf.text
    stale = (await _node(db_session, b["id"])).version
    await _move(s.moderator, db_session, b["id"], group["id"])
    conflict = await be.post(
        f"/nodes/{b['id']}/move",
        json={"base_version": stale, "new_parent_id": str(branch.id)},
    )
    assert (conflict.status_code, conflict.json()["code"]) == (409, "FIELD_CONFLICT")
    assert conflict.json()["conflicts"][0]["field"] == "parent"


@pytest.mark.spec("5.1")
@pytest.mark.spec("SEC-AUTHZ-05")
@pytest.mark.tc("TC-BR-01")
async def test_move_across_branches(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    backend = await s.branch(db_session, s.backend)
    frontend = await s.branch(db_session, s.frontend)
    group = await _leaf(s.backend_expert, s, backend.id, "Модуль")
    leaf = await _leaf(s.backend_expert, s, group["id"], "Экран", o="1", r="2", p="3")
    await _leaf(s.frontend_expert, s, frontend.id, "Форма", o="1", r="2", p="3")

    # эксперт: в чужую ветку — 403, в другую фазу своей дисциплины — тоже 403
    foreign = await _move(s.backend_expert, db_session, group["id"], frontend.id)
    assert foreign.status_code == 403, foreign.text
    other_phase = (
        await db_session.scalars(
            select(Node).where(
                Node.project_id == s.pid,
                Node.discipline_id == s.backend,
                Node.kind == backend.kind,
                Node.id != backend.id,
            )
        )
    ).first()
    if other_phase is not None:
        assert (
            await _move(s.backend_expert, db_session, group["id"], other_phase.id)
        ).status_code == 403

    # модератор: обе ветки «готово» → «черновик», у поддерева новая дисциплина
    for phase, discipline in ((backend.phase_id, s.backend), (frontend.phase_id, s.frontend)):
        await _force_done(db_session, s, phase, discipline)
    across = await _move(s.moderator, db_session, group["id"], frontend.id)
    assert across.status_code == 200, across.text
    changes = {
        (c["discipline_id"], c["was"], c["status"]) for c in across.json()["branch_statuses"]
    }
    assert changes == {
        (str(s.backend), "done", "draft"),
        (str(s.frontend), "done", "draft"),
    }
    for node_id in (group["id"], leaf["id"]):
        assert (await _node(db_session, node_id)).discipline_id == s.frontend
    assert await _children(db_session, frontend.id) == ["Модуль", "Форма"]


@pytest.mark.spec("BR-TREE-02")
@pytest.mark.tc("TC-TREE-01")
@pytest.mark.tc("TC-BR-01")
async def test_split(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Отчёты", o="40", r="60", p="100")
    assert (await _create(s.backend_expert, s.pid, leaf["id"], title="x")).status_code == 422
    patched = await s.backend_expert.patch(
        f"/nodes/{leaf['id']}", json={"base_version": 1, "changes": {"multiplier": 2}}
    )
    assert patched.status_code == 200, patched.text
    before_e = patched.json()["node"]["e"]

    await _force_done(db_session, s, branch.phase_id, s.backend)
    split = await s.backend_expert.post(f"/nodes/{leaf['id']}/split", json={"base_version": 2})
    assert split.status_code == 200, split.text
    body = split.json()
    by_id = {n["id"]: n for n in body["nodes"]}
    node = by_id[leaf["id"]]
    [child] = [n for n in body["nodes"] if n["parent_id"] == leaf["id"]]
    assert (node["o"], node["r"], node["p"], node["multiplier"]) == (None, None, None, 1)
    assert (child["title"], child["o"], child["r"], child["p"], child["multiplier"]) == (
        "Отчёты — часть 1",
        "40",
        "60",
        "100",
        2,
    )
    assert node["e"] == before_e  # TC-TREE-01: E узла не меняется
    assert [c["status"] for c in body["branch_statuses"]] == ["draft"]
    [entry] = (
        await db_session.scalars(
            select(NodeHistory.changes).where(
                NodeHistory.node_id == uuid.UUID(leaf["id"]),
                NodeHistory.action == NodeAction.SPLIT,
            )
        )
    ).all()
    assert entry["o"] == ["40", None]
    assert entry["multiplier"] == [2, 1]

    # узел с детьми не разбивают; длинное название обрезается под суффикс
    again = await s.backend_expert.post(f"/nodes/{leaf['id']}/split", json={"base_version": 3})
    assert again.status_code == 422, again.text
    long_title = "Я" * 200
    assert len(split_title(long_title)) == 200
    assert split_title(long_title).endswith(" — часть 1")


@pytest.mark.spec("BR-TREE-03")
@pytest.mark.tc("TC-TREE-01")
@pytest.mark.tc("TC-BR-01")
async def test_collapse(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(s.backend_expert, s, branch.id, "Модуль")
    a = await _leaf(s.backend_expert, s, group["id"], "A", o="8", r="12", p="20")
    b = await _leaf(s.backend_expert, s, group["id"], "B", o="4", r="6", p="8", multiplier=2)
    sub = await _leaf(s.backend_expert, s, group["id"], "Подмодуль")
    deep = await _leaf(s.backend_expert, s, sub["id"], "Пусто")

    hint = await s.backend_expert.get(f"/nodes/{group['id']}/collapse")
    assert hint.status_code == 200, hint.text
    assert hint.json() == {"o": "16", "r": "24", "p": "36", "multiplier": 1}

    await _force_done(db_session, s, branch.phase_id, s.backend)
    version = (await _node(db_session, group["id"])).version
    done = await s.backend_expert.post(
        f"/nodes/{group['id']}/collapse", json={"base_version": version}
    )
    assert done.status_code == 200, done.text
    body = done.json()
    node = {n["id"]: n for n in body["nodes"]}[group["id"]]
    assert (node["o"], node["r"], node["p"], node["multiplier"]) == ("16", "24", "36", 1)
    assert set(body["deleted_ids"]) == {a["id"], b["id"], sub["id"], deep["id"]}
    assert [c["status"] for c in body["branch_statuses"]] == ["draft"]
    batches = {(await _node(db_session, i)).deleted_batch_id for i in body["deleted_ids"]}
    assert batches == {uuid.UUID(body["batch_id"])}  # одним пакетом
    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{s.pid}") if e["event"] == "node.deleted"]
    assert event["data"]["batch_id"] == body["batch_id"]

    # свёрнутый узел — лист: повторно не сворачивается; свои O/R/P округляются
    again = await s.backend_expert.post(
        f"/nodes/{group['id']}/collapse", json={"base_version": node["version"]}
    )
    assert again.status_code == 422
    other = await _leaf(s.backend_expert, s, branch.id, "Ещё")
    await _leaf(s.backend_expert, s, other["id"], "Часть", o="1", r="2", p="3")
    version = (await _node(db_session, other["id"])).version
    custom = await s.backend_expert.post(
        f"/nodes/{other['id']}/collapse",
        json={"base_version": version, "o": "1.2", "r": "2", "p": "5"},
    )
    assert custom.status_code == 200, custom.text
    leaf = {n["id"]: n for n in custom.json()["nodes"]}[other["id"]]
    assert (leaf["o"], leaf["p"]) == ("1", "5")


async def test_duplicate(world: World, db_session: AsyncSession) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(s.backend_expert, s, branch.id, "Модуль")
    await _leaf(s.backend_expert, s, group["id"], "A", o="8", r="12", p="20")
    await _leaf(s.backend_expert, s, group["id"], "B", o="0", r="0", p="0")
    await _leaf(s.backend_expert, s, branch.id, "Сосед")  # встаёт первым
    await _leaf(s.backend_expert, s, branch.id, "Начало")
    await _review(reviewer, group["id"])

    copy = await s.backend_expert.post(f"/nodes/{group['id']}/duplicate")
    assert copy.status_code == 201, copy.text
    body = copy.json()
    new = [n for n in body["nodes"] if n["title"] in ("Модуль", "A", "B")]
    new = [n for n in new if n["id"] != group["id"]]
    assert sorted(n["title"] for n in new) == ["A", "B", "Модуль"]
    assert all(n["reviewed_by"] is None for n in new)
    assert await _children(db_session, branch.id) == ["Начало", "Сосед", "Модуль", "Модуль"]
    [root] = [n for n in new if n["title"] == "Модуль"]
    assert await _children(db_session, root["id"]) == ["B", "A"]
    assert {n["o"] for n in new if n["title"] == "B"} == {"0"}
    assert (await _node(db_session, group["id"])).reviewed_by is not None  # оригинал не трогаем
    assert (await _node(db_session, branch.id)).reviewed_by is None  # добавление — с родителя
