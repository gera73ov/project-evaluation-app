"""CORE-015: создание и изменение узлов — предложение типа, округление, ошибки 422/409/423,
конфликт полей (TC-CONC-01, TC-CONC-02), пример 15.3, история и версии, права эксперта
(SEC-AUTHZ-05), сброс «готово» (BR-BR-02)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.enums import BranchStatusValue, NodeKind, SystemRole
from estimator.db.models.dictionaries import CommentTag, NodeType, Phase
from estimator.db.models.projects import BranchStatus
from estimator.db.models.tree import ChangeLog, Node, NodeHistory
from estimator.db.uuid7 import uuid7
from estimator.realtime.bus.memory import InMemoryBus
from estimator.realtime.locks import iface as locks
from estimator.services.tree import edit
from estimator.services.tree.load import count_live_nodes
from estimator.services.tree.positions import keys_after
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.helpers import create_project, discipline
from tests.integration.core.test_tree_api import _coverage_active

pytestmark = [pytest.mark.integration, pytest.mark.spec("15.3"), pytest.mark.spec("FR-TREE-32")]


@dataclass
class Setup:
    pid: uuid.UUID
    moderator: Actor
    backend_expert: Actor
    frontend_expert: Actor
    backend: uuid.UUID
    frontend: uuid.UUID

    async def branch(self, db: AsyncSession, discipline_id: uuid.UUID) -> Node:
        return (
            await db.scalars(
                select(Node)
                .where(
                    Node.project_id == self.pid,
                    Node.discipline_id == discipline_id,
                    Node.kind == NodeKind.DISCIPLINE,
                )
                .order_by(Node.position)
            )
        ).first()


async def _setup(world: World, db: AsyncSession, *, launch: bool = True) -> Setup:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db, "Бэкенд")
    frontend = await discipline(db, "Фронтенд")
    for d in (backend, frontend):
        added = await moderator.post(f"/projects/{pid}/disciplines", json={"discipline_id": str(d)})
        assert added.status_code == 201, added.text
    be, fe = await world.actor(), await world.actor()
    team = await moderator.put(
        f"/projects/{pid}/members",
        json={
            "members": [
                {"user_id": str(moderator.id), "role": "moderator"},
                {"user_id": str(be.id), "role": "expert", "discipline_id": str(backend)},
                {"user_id": str(fe.id), "role": "expert", "discipline_id": str(frontend)},
            ]
        },
    )
    assert team.status_code == 200, team.text
    if launch:
        assert (
            await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
        ).status_code == 200
    return Setup(pid, moderator, be, fe, backend, frontend)


async def _create(actor: Actor, pid: uuid.UUID, parent: Any, **body: Any) -> Any:
    payload = {"parent_id": str(parent), "title": body.pop("title", "Авторизация")} | body
    return await actor.post(f"/projects/{pid}/nodes", json=payload)


async def _patch(actor: Actor, node_id: Any, base: int, **changes: Any) -> Any:
    return await actor.patch(f"/nodes/{node_id}", json={"base_version": base, "changes": changes})


async def _type_ids(db: AsyncSession) -> dict[str, uuid.UUID]:
    rows = await db.execute(select(NodeType.icon, NodeType.id).where(NodeType.project_id.is_(None)))
    return dict(rows.all())


@pytest.mark.spec("FR-TREE-01")
async def test_create_suggests_type_and_drafts_branch(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    types = await _type_ids(db_session)
    branch = await s.branch(db_session, s.backend)
    first = await _create(s.backend_expert, s.pid, branch.id, title="  Личный кабинет ")
    assert first.status_code == 201, first.text
    body = first.json()
    node = body["node"]
    assert (node["title"], node["kind"], node["version"]) == ("Личный кабинет", "item", 1)
    assert node["type_id"] == str(types["module"])  # профиль «Модуль → Функция»: первый тип
    assert (node["o"], node["r"], node["p"], node["multiplier"]) == (None, None, None, 1)
    assert node["leaf_state"] == "empty"
    assert body["branch_status"] == {
        "phase_id": str(branch.phase_id),
        "discipline_id": str(s.backend),
        "status": "draft",
        "was": "not_started",
    }
    assert [a["id"] for a in body["ancestors"]] == [str(branch.id), str(branch.parent_id)]
    assert body["totals"]["e"] == "0.00"

    child = await _create(s.backend_expert, s.pid, node["id"], title="Вход")
    assert child.json()["node"]["type_id"] == str(types["function"])  # следующий в цепочке
    grandchild = await _create(s.backend_expert, s.pid, child.json()["node"]["id"], title="Шаг")
    assert grandchild.json()["node"]["type_id"] == str(types["function"])  # иначе — тип родителя
    work = await _create(s.backend_expert, s.pid, branch.id, title="Прочее", type_id=None)
    assert work.json()["node"]["type_id"] == str(types["work"])  # BR-TREE-08
    assert work.json()["branch_status"] is None  # ветка уже «черновик»

    # порядок: after_id — сразу за соседом, без after_id — первым
    first_id = node["id"]
    after = await _create(s.backend_expert, s.pid, branch.id, title="Между", after_id=first_id)
    top = await _create(s.backend_expert, s.pid, branch.id, title="Первый")
    positions = {
        n.title: n.position
        for n in (await db_session.scalars(select(Node).where(Node.parent_id == branch.id))).all()
    }
    order = sorted(positions, key=positions.__getitem__)
    assert order == ["Первый", "Прочее", "Личный кабинет", "Между"]
    assert after.status_code == top.status_code == 201

    history = (
        await db_session.scalars(
            select(NodeHistory).where(NodeHistory.node_id == uuid.UUID(first_id))
        )
    ).one()
    assert history.changes == {
        "title": [None, "Личный кабинет"],
        "type": [None, str(types["module"])],
    }
    await deliver_events(db_session)
    names = [e["event"] for e in events.on(f"project:{s.pid}")]
    assert names[-7:] == ["node.created", "branch.status"] + ["node.created"] * 5
    created = [e for e in events.on(f"project:{s.pid}") if e["event"] == "node.created"]
    assert created[-6]["data"]["node"]["id"] == first_id
    status_events = [e for e in events.on(f"project:{s.pid}") if e["event"] == "branch.status"]
    assert status_events[-1]["data"]["author"]["id"] == str(s.backend_expert.id)
    logged = (
        await db_session.scalars(select(ChangeLog.version).where(ChangeLog.project_id == s.pid))
    ).all()
    assert len(logged) == len(set(logged))  # одна версия — одно событие


@pytest.mark.spec("BR-TREE-05")
@pytest.mark.spec("BR-TREE-07")
async def test_create_errors(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    url = s.pid

    async def code(response: Any) -> tuple[int, str]:
        return response.status_code, response.json()["code"]

    assert await code(await _create(s.moderator, url, branch.id, title="две\nстроки")) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code(await _create(s.moderator, url, branch.id, title="   ")) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code(await _create(s.moderator, url, uuid.uuid4())) == (422, "VALIDATION_FAILED")
    assert await code(await _create(s.moderator, url, branch.id, type_id=str(uuid.uuid4()))) == (
        422,
        "VALIDATION_FAILED",
    )
    assert await code(await _create(s.moderator, url, branch.id, o="100000")) == (
        422,
        "VALUE_OUT_OF_RANGE",
    )
    pm = (
        await db_session.scalars(
            select(Node)
            .join(Phase, Phase.id == Node.phase_id)
            .where(Node.project_id == s.pid, Phase.is_cross_cutting, Node.kind == NodeKind.PHASE)
        )
    ).one()
    assert await code(await _create(s.moderator, url, pm.id)) == (409, "CROSS_CUTTING_PHASE_LOCKED")
    phase = await db_session.get(Node, branch.parent_id)
    assert await code(await _create(s.moderator, url, phase.id)) == (422, "VALIDATION_FAILED")

    # лист с оценкой — только «Разбить» (BR-TREE-02)
    leaf = (await _create(s.moderator, url, branch.id, o="8", r="12", p="20")).json()["node"]
    assert (leaf["o"], leaf["r"], leaf["p"]) == ("8", "12", "20")
    assert await code(await _create(s.moderator, url, leaf["id"])) == (422, "VALIDATION_FAILED")

    # глубина: 8 уровней ниже ветки
    parent = branch.id
    for level in range(1, 9):
        made = await _create(s.moderator, url, parent, title=f"Уровень {level}")
        assert made.status_code == 201, (level, made.text)
        parent = made.json()["node"]["id"]
    deep = await _create(s.moderator, url, parent, title="Уровень 9")
    assert await code(deep) == (422, "DEPTH_LIMIT")
    assert deep.json()["max_depth"] == 8

    monkeypatch.setattr(edit, "NODES_LIMIT", 0)
    full = await _create(s.moderator, url, branch.id)
    assert await code(full) == (409, "NODES_LIMIT")
    assert full.json()["requested"] == 1


@pytest.mark.spec("SEC-AUTHZ-05")
async def test_expert_rights(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    backend = await s.branch(db_session, s.backend)
    frontend = await s.branch(db_session, s.frontend)
    mine = (await _create(s.backend_expert, s.pid, backend.id)).json()["node"]
    foreign = (await _create(s.frontend_expert, s.pid, frontend.id)).json()["node"]

    assert (await _patch(s.backend_expert, mine["id"], 1, o="8")).status_code == 200
    denied = await _patch(s.backend_expert, foreign["id"], 1, o="8")
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    assert (await _create(s.backend_expert, s.pid, frontend.id)).status_code == 403
    comment = await _patch(
        s.backend_expert, foreign["id"], 1, comment_lines=[{"tag_id": None, "text": "x"}]
    )
    assert comment.status_code == 403

    presale = await world.actor(SystemRole.PRESALE)
    await s.moderator.put(
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
                {"user_id": str(presale.id), "role": "presale"},
            ]
        },
    )
    assert (await _patch(presale, mine["id"], 2, o="10")).status_code == 403
    outsider = await world.actor()
    assert (await _patch(outsider, mine["id"], 2, o="10")).status_code == 404
    # модератор правит любую ветку
    assert (await _patch(s.moderator, foreign["id"], 1, o="4")).status_code == 200

    # «Завершена» — правка запрещена статусом проекта
    await s.moderator.post(f"/projects/{s.pid}/status", json={"to": "consolidation"})
    await db_session.execute(
        update(BranchStatus).where(BranchStatus.project_id == s.pid).values(status="done")
    )
    await s.moderator.post(f"/projects/{s.pid}/status", json={"to": "completed"})
    closed = await _patch(s.moderator, mine["id"], 2, o="12")
    assert (closed.status_code, closed.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")


async def test_patch_example_rounding_and_errors(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = (await _create(s.backend_expert, s.pid, branch.id, o="8", r="12", p="20")).json()["node"]
    response = await _patch(s.backend_expert, leaf["id"], 1, r="16", p="30")  # пример 15.3
    assert response.status_code == 200, response.text
    body = response.json()
    node = body["node"]
    assert (node["o"], node["r"], node["p"], node["version"]) == ("8", "16", "30", 2)
    assert (node["e"], node["sigma"]) == ("17.00", "3.67")
    assert node["field_versions"] == {"r": 2, "p": 2}
    assert body["ancestors"][0] == {"id": str(branch.id), "e": "17.00", "sigma": "3.67"}
    assert body["totals"]["e"] != "0.00"
    assert body["rounded"] == []

    rounded = await _patch(s.backend_expert, leaf["id"], 2, o="12,3", multiplier=2)
    assert rounded.json()["node"]["o"] == "12.5"
    assert rounded.json()["rounded"] == ["o"]
    big = await _patch(s.backend_expert, leaf["id"], 3, p="99999.8")
    assert (big.status_code, big.json()["code"], big.json()["field"]) == (
        422,
        "VALUE_OUT_OF_RANGE",
        "p",
    )
    ok = await _patch(s.backend_expert, leaf["id"], 3, p="99999.7")  # округляется до 99 999,5
    assert ok.json()["node"]["p"] == "99999.5"
    # O > R не мешает сохранить, лист не входит в суммы (FR-TREE-22)
    bad = await _patch(s.backend_expert, leaf["id"], 4, o="50", r="10")
    assert bad.status_code == 200
    assert bad.json()["node"]["leaf_state"] == "invalid"

    child = await _create(s.backend_expert, s.pid, branch.id, title="Узел")
    parent_id = child.json()["node"]["id"]
    await _create(s.backend_expert, s.pid, parent_id, title="Лист")
    has = await _patch(s.backend_expert, parent_id, 1, o="5")
    assert (has.status_code, has.json()["code"]) == (422, "NODE_HAS_CHILDREN")
    renamed = await _patch(s.backend_expert, parent_id, 1, title="Узел 2")
    assert renamed.status_code == 200
    empty = await s.backend_expert.patch(
        f"/nodes/{parent_id}", json={"base_version": 2, "changes": {}}
    )
    assert empty.status_code == 422
    branch_title = await _patch(s.moderator, branch.id, 1, title="Другое")
    assert (branch_title.status_code, branch_title.json()["code"]) == (422, "VALIDATION_FAILED")
    gone = await s.moderator.patch(
        f"/nodes/{uuid.uuid4()}", json={"base_version": 1, "changes": {"o": "1"}}
    )
    assert gone.status_code == 404

    versions = (
        await db_session.scalars(
            select(NodeHistory.node_version)
            .where(NodeHistory.node_id == uuid.UUID(leaf["id"]))
            .order_by(NodeHistory.node_version)
        )
    ).all()
    assert list(versions) == [1, 2, 3, 4, 5]
    last = (
        await db_session.scalars(
            select(NodeHistory.changes)
            .where(NodeHistory.node_id == uuid.UUID(leaf["id"]))
            .order_by(NodeHistory.node_version.desc())
        )
    ).first()
    assert last == {"o": ["12.5", "50"], "r": ["16", "10"]}


@pytest.mark.tc("TC-CONC-01")
@pytest.mark.tc("TC-CONC-02")
async def test_field_conflicts(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = (await _create(s.backend_expert, s.pid, branch.id, o="8", r="12", p="20")).json()["node"]
    nid = leaf["id"]

    # TC-CONC-01: разные поля с одной базовой версией — обе правки применены
    assert (await _patch(s.backend_expert, nid, 1, r="16")).status_code == 200
    second = await _patch(s.moderator, nid, 1, p="30")
    assert second.status_code == 200, second.text
    assert (second.json()["node"]["r"], second.json()["node"]["p"]) == ("16", "30")

    # TC-CONC-02: то же поле с той же базовой версией — 409 с текущим значением
    conflict = await _patch(s.moderator, nid, 1, r="18")
    assert conflict.status_code == 409
    problem = conflict.json()
    assert problem["code"] == "FIELD_CONFLICT"
    assert problem["current_version"] == 3
    [entry] = problem["conflicts"]
    assert entry["field"] == "r"
    assert entry["current"] == "16"
    assert entry["changed_at"].endswith("Z")
    assert entry["changed_by"]
    # «Оставить моё»: повтор с текущей версией проходит
    assert (await _patch(s.moderator, nid, 3, r="18")).status_code == 200
    # своя же предыдущая правка — не конфликт
    assert (await _patch(s.moderator, nid, 3, r="19")).status_code == 200
    # то же значение — правки нет, версия не растёт
    same = await _patch(s.moderator, nid, 5, r="19")
    assert same.json()["node"]["version"] == 5


@pytest.mark.spec("FR-TREE-31")
async def test_cell_locked(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = (await _create(s.backend_expert, s.pid, branch.id)).json()["node"]
    checked: list[str] = []

    class Locked:
        async def assert_not_locked(
            self, project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, user_id: uuid.UUID
        ) -> None:
            checked.append(field)
            if field == "r" and user_id != s.backend_expert.id:
                raise ApiError(
                    "CELL_LOCKED",
                    locked_by={
                        "id": str(s.backend_expert.id),
                        "name": "И. Иванов",
                        "initials": "ИИ",
                    },
                    field="r",
                    node_id=str(node_id),
                )

    previous = locks.set_lock_checker(Locked())
    try:
        locked = await _patch(s.moderator, leaf["id"], 1, r="12")
        assert (locked.status_code, locked.json()["code"]) == (423, "CELL_LOCKED")
        assert (await _patch(s.moderator, leaf["id"], 1, o="8", title="Новое")).status_code == 200
        assert (await _patch(s.backend_expert, leaf["id"], 2, r="12")).status_code == 200
    finally:
        locks.set_lock_checker(previous)
    assert set(checked) >= {"o", "r", "title"}


@pytest.mark.spec("BR-BR-02")
@pytest.mark.spec("R-03")
async def test_done_reset_and_comment(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = (await _create(s.backend_expert, s.pid, branch.id, o="8", r="12", p="20")).json()["node"]
    key = (s.pid, branch.phase_id, s.backend)

    async def set_done() -> None:
        await db_session.execute(
            update(BranchStatus)
            .where(
                BranchStatus.project_id == s.pid,
                BranchStatus.phase_id == branch.phase_id,
                BranchStatus.discipline_id == s.backend,
            )
            .values(status=BranchStatusValue.DONE)
        )

    async def status() -> BranchStatusValue:
        return (await db_session.get(BranchStatus, key, populate_existing=True)).status

    tag = (await db_session.scalars(select(CommentTag.id))).first()
    await set_done()
    lines = [{"tag_id": str(tag), "text": "Через Keycloak"}, {"tag_id": None, "text": "Без SSO"}]
    commented = await _patch(s.backend_expert, leaf["id"], 1, comment_lines=lines, title="Вход")
    assert commented.status_code == 200, commented.text
    assert commented.json()["node"]["comment_lines"] == lines
    assert commented.json()["branch_status"] is None
    assert await status() is BranchStatusValue.DONE  # комментарий и название не сбрасывают

    reset = await _patch(s.backend_expert, leaf["id"], 2, multiplier=3)
    assert reset.json()["branch_status"]["was"] == "done"
    assert await status() is BranchStatusValue.DRAFT

    await set_done()
    added = await _create(s.backend_expert, s.pid, branch.id, title="Ещё")
    assert added.json()["branch_status"]["status"] == "draft"

    unknown = await _patch(
        s.backend_expert, leaf["id"], 3, comment_lines=[{"tag_id": str(uuid.uuid4()), "text": "x"}]
    )
    assert (unknown.status_code, unknown.json()["code"]) == (422, "VALIDATION_FAILED")
    long = await _patch(
        s.backend_expert,
        leaf["id"],
        3,
        comment_lines=[{"tag_id": None, "text": "а" * 1500}, {"tag_id": None, "text": "б" * 600}],
    )
    assert long.status_code == 422
    cleared = await _patch(s.backend_expert, leaf["id"], 3, comment_lines=[])
    assert cleared.json()["node"]["comment_lines"] is None


@pytest.mark.spec("NFR-PERF-03")
async def test_patch_in_5000_nodes_is_fast(world: World, db_session: AsyncSession) -> None:
    """Правка на дереве из 5 000 узлов (предел BR-TREE-06) не деградирует.

    NFR-PERF-03 (≤ 300 мс p95) меряют E2E на стенде; здесь — порог от регрессий с запасом на
    общий CI-раннер. Кэш итогов CORE-026 уберёт полный пересчёт из ответа правки."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    current = await count_live_nodes(db_session, s.pid)
    rows: list[dict[str, Any]] = []
    parents = [branch.id]
    for i, position in enumerate(keys_after("b00", 5000 - current)):
        node_id = uuid7()
        group = i % 10 == 0
        rows.append(
            {
                "id": node_id,
                "project_id": s.pid,
                "parent_id": branch.id if group else parents[-1],
                "kind": "item",
                "phase_id": branch.phase_id,
                "discipline_id": branch.discipline_id,
                "title": f"Узел {i}",
                "position": position,
                "o": None if group else Decimal(1),
                "r": None if group else Decimal(2),
                "p": None if group else Decimal(4),
                "multiplier": 1,
            }
        )
        if group:
            parents.append(node_id)
    await db_session.execute(Node.__table__.insert(), rows)
    leaf = rows[1]["id"]
    timings = []
    for base, value in enumerate(("2", "3", "4", "5", "6"), start=1):
        started = time.perf_counter()
        response = await _patch(s.backend_expert, leaf, base, r=value)
        timings.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    budget = 1.5 if _coverage_active() else 0.5
    assert sorted(timings)[2] < budget, f"правка за {timings} с (бюджет {budget} с)"
