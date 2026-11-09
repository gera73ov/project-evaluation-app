"""RT-005 (захват ячеек) и RT-007 (догрузка после разрыва) на живом сервере с REST ядра.

SPEC FR-TREE-31, FR-TREE-33, ARCH-02, 15.3 (423 ``CELL_LOCKED``), TC-CONC-03, TC-CONC-04.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select, text

from estimator.db.enums import NodeKind, SystemRole
from estimator.db.models.dictionaries import Discipline, Phase
from estimator.db.models.tree import ChangeLog, Node
from estimator.realtime import changes
from estimator.realtime.locks import lock_key
from tests.integration.rt.conftest import Client, Stage
from tests.integration.rt.test_ws_api import validate_reply

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-31")]


@dataclass
class Tree:
    pid: uuid.UUID
    moderator: str
    expert_a: str
    expert_b: str
    other: str  # эксперт другой дисциплины
    leaf: uuid.UUID
    a_id: uuid.UUID
    version: int


async def _tree(stage: Stage) -> Tree:
    mod_id, moderator = await stage.user(SystemRole.MODERATOR)
    a_id, expert_a = await stage.user()
    b_id, expert_b = await stage.user()
    o_id, other = await stage.user()
    async with stage.data() as db:
        phases = dict((await db.execute(select(Phase.name, Phase.id).where(Phase.is_active))).all())
        disc = dict((await db.execute(select(Discipline.name, Discipline.id))).all())
    created = await stage.rest("POST", moderator, "/projects", json={
        "name": "Портал дилеров", "customer": "ООО Ромашка",
        "phase_ids": [str(phases["Разработка"])],
    })  # fmt: skip
    assert created.status_code == 201, created.text
    pid = uuid.UUID(created.json()["project"]["id"])
    for name in ("Бэкенд", "Фронтенд"):
        added = await stage.rest("POST", moderator, f"/projects/{pid}/disciplines",
                                 json={"discipline_id": str(disc[name])})  # fmt: skip
        assert added.status_code == 201, added.text
    team = await stage.rest("PUT", moderator, f"/projects/{pid}/members", json={"members": [
        {"user_id": str(mod_id), "role": "moderator"},
        {"user_id": str(a_id), "role": "expert", "discipline_id": str(disc["Бэкенд"])},
        {"user_id": str(b_id), "role": "expert", "discipline_id": str(disc["Бэкенд"])},
        {"user_id": str(o_id), "role": "expert", "discipline_id": str(disc["Фронтенд"])},
    ]})  # fmt: skip
    assert team.status_code == 200, team.text
    launched = await stage.rest("POST", moderator, f"/projects/{pid}/status",
                                json={"to": "estimation"})  # fmt: skip
    assert launched.status_code == 200, launched.text
    async with stage.data() as db:
        branch = (await db.scalars(select(Node.id).where(
            Node.project_id == pid, Node.discipline_id == disc["Бэкенд"],
            Node.kind == NodeKind.DISCIPLINE,
        ))).first()  # fmt: skip
    leaf = await stage.rest(
        "POST", expert_a, f"/projects/{pid}/nodes",
        json={"parent_id": str(branch), "title": "Авторизация", "r": "8"},
    )  # fmt: skip
    assert leaf.status_code == 201, leaf.text
    body = leaf.json()
    return Tree(pid, moderator, expert_a, expert_b, other, uuid.UUID(body["node"]["id"]), a_id,
                body["project_version"])  # fmt: skip


async def _open(stage: Stage, tree: Tree, sid: str, **sub: object) -> Client:
    client = await stage.connect(sid)
    reply = await client.subscribe(tree.pid, **sub)
    assert reply["type"] == "ack", reply
    return client


def _lock_args(tree: Tree, field: str = "r", **extra: object) -> dict[str, object]:
    return {"project_id": str(tree.pid), "node_id": str(tree.leaf), "field": field, **extra}


async def _patch(stage: Stage, sid: str, node: uuid.UUID, **changes_: object):
    async with stage.data() as db:
        version = await db.scalar(select(Node.version).where(Node.id == node))
    return await stage.rest("PATCH", sid, f"/nodes/{node}",
                            json={"base_version": version, "changes": changes_})  # fmt: skip


@pytest.mark.tc("TC-CONC-04")
async def test_locked_cell_rejects_other_editor_until_saved(stage: Stage) -> None:
    tree = await _tree(stage)
    a, b = await _open(stage, tree, tree.expert_a), await _open(stage, tree, tree.expert_b)
    got = await a.call("lock", **_lock_args(tree))
    validate_reply(got)
    assert got["type"] == "ack"
    assert got["result"]["expires_at"].endswith("Z")
    seen = await b.event("cell.locked")
    assert seen["data"]["user"]["id"] == str(tree.a_id)
    assert seen["data"]["forced"] is False

    busy = await b.call("lock", **_lock_args(tree))
    validate_reply(busy)
    assert busy["code"] == "CELL_LOCKED"
    assert busy["locked_by"]["id"] == str(tree.a_id)
    assert (await b.call("lock", **_lock_args(tree, "o")))["type"] == "ack"  # соседнее поле

    rejected = await _patch(stage, tree.expert_b, tree.leaf, r="18")
    assert rejected.status_code == 423
    assert rejected.json()["code"] == "CELL_LOCKED"
    assert rejected.json()["locked_by"]["id"] == str(tree.a_id)
    assert rejected.json()["field"] == "r"

    saved = await _patch(stage, tree.expert_a, tree.leaf, r="16")
    assert saved.status_code == 200, saved.text
    for client in (a, b):
        unlocked = await client.wait(lambda m: m.get("event") == "cell.unlocked"
                                     and m["data"]["field"] == "r")  # fmt: skip
        assert unlocked["data"]["reason"] == "saved"
    assert (await b.call("lock", **_lock_args(tree)))["type"] == "ack"


async def test_moderator_force_takes_over_and_expert_cannot(stage: Stage) -> None:
    tree = await _tree(stage)
    a, b = await _open(stage, tree, tree.expert_a), await _open(stage, tree, tree.expert_b)
    m = await _open(stage, tree, tree.moderator)
    await a.call("lock", **_lock_args(tree))
    denied = await b.call("lock", **_lock_args(tree, force=True))
    assert denied["code"] == "FORBIDDEN"
    taken = await m.call("lock", **_lock_args(tree, force=True))
    assert taken["type"] == "ack"
    forced = await a.wait(lambda x: x.get("event") == "cell.unlocked")
    assert forced["data"]["reason"] == "forced"
    assert forced["data"]["user_id"] == str(tree.a_id)
    relocked = await a.wait(lambda x: x.get("event") == "cell.locked" and x["data"]["forced"])
    assert relocked["data"]["user"]["id"] != str(tree.a_id)
    beat = await a.call("heartbeat", locks=[{"node_id": str(tree.leaf), "field": "r"}])
    assert beat["result"] == {"extended": [], "lost": [{"node_id": str(tree.leaf), "field": "r"}]}


async def test_rights_scope_and_subscription(stage: Stage) -> None:
    tree = await _tree(stage)
    other = await _open(stage, tree, tree.other)
    foreign = await other.call("lock", **_lock_args(tree))
    assert foreign["code"] == "FORBIDDEN"
    stranger = await stage.connect(tree.expert_a)
    assert (await stranger.call("lock", **_lock_args(tree)))["code"] == "NOT_FOUND"
    await stranger.subscribe(tree.pid)
    missing = await stranger.call("lock", **{**_lock_args(tree), "node_id": str(uuid.uuid4())})
    assert missing["code"] == "NOT_FOUND"
    # комментарий захватывается по праву comment.write
    assert (await stranger.call("lock", **_lock_args(tree, "comment")))["type"] == "ack"


async def test_unlock_disconnect_heartbeat_and_expiry(stage: Stage, redis_client) -> None:
    tree = await _tree(stage)
    a, b = await _open(stage, tree, tree.expert_a), await _open(stage, tree, tree.expert_b)
    await a.call("lock", **_lock_args(tree))
    await a.call("unlock", **_lock_args(tree))
    assert (await b.event("cell.unlocked"))["data"]["reason"] == "released"

    await a.call("lock", **_lock_args(tree))
    beat = await a.call("heartbeat", locks=[{"node_id": str(tree.leaf), "field": "r"}])
    assert [x["field"] for x in beat["result"]["extended"]] == ["r"]
    assert beat["result"]["lost"] == []
    # 30 с без продления: ключ истёк в Redis, часы ушли вперёд — «expired»
    await redis_client.delete(lock_key(tree.pid, tree.leaf, "r"))
    stage.clock.now += 31  # type: ignore[attr-defined]
    assert (await b.event("cell.unlocked"))["data"]["reason"] == "expired"

    await a.call("lock", **_lock_args(tree, "p"))
    await a.conn.close()
    gone = await b.wait(lambda m: m.get("event") == "cell.unlocked" and m["data"]["field"] == "p")
    assert gone["data"]["reason"] == "disconnected"


@pytest.mark.tc("TC-CONC-03")
@pytest.mark.spec("FR-TREE-33")
async def test_reconnect_with_since_gets_missed_changes(stage: Stage) -> None:
    tree = await _tree(stage)
    b = await _open(stage, tree, tree.expert_b, since=tree.version)
    await b.conn.close()  # «разрыв»
    for value in ("10", "12"):
        response = await _patch(stage, tree.expert_a, tree.leaf, r=value)
        assert response.status_code == 200, response.text
    b = await stage.connect(tree.expert_b)
    reply = await b.subscribe(tree.pid, since=tree.version)
    assert reply["result"]["resync"] is False
    current = reply["result"]["project_version"]
    first = await b.event("node.updated")
    second = await b.event("node.updated")
    assert [first["data"]["node"]["r"], second["data"]["node"]["r"]] == ["10", "12"]
    assert first["project_version"] < second["project_version"] <= current

    rest = await stage.rest("GET", tree.expert_b, f"/projects/{tree.pid}/changes",
                            params={"since": tree.version})  # fmt: skip
    assert rest.status_code == 200, rest.text
    body = rest.json()
    assert (body["from_version"], body["to_version"]) == (tree.version, current)
    assert [e["project_version"] for e in body["events"]] == [
        first["project_version"], second["project_version"],
    ]  # fmt: skip
    empty = await stage.rest("GET", tree.expert_b, f"/projects/{tree.pid}/changes",
                             params={"since": current})  # fmt: skip
    assert empty.json()["events"] == []
    ahead = await stage.rest("GET", tree.expert_b, f"/projects/{tree.pid}/changes",
                             params={"since": current + 5})  # fmt: skip
    assert ahead.status_code == 410
    assert ahead.json()["code"] == "VERSION_TOO_OLD"
    assert ahead.json()["current_version"] == current


@pytest.mark.spec("NFR-REL-06")
async def test_too_old_version_needs_full_reload_and_purge_keeps_boundary(stage: Stage) -> None:
    tree = await _tree(stage)
    for value in ("10", "12", "14"):
        assert (await _patch(stage, tree.expert_a, tree.leaf, r=value)).status_code == 200
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
    async with stage.data() as db:
        versions = (await db.scalars(select(ChangeLog.version).where(
            ChangeLog.project_id == tree.pid).order_by(ChangeLog.version))).all()  # fmt: skip
        # все записи, кроме последней, — старше 7 дней
        await db.execute(text(
            "UPDATE change_log SET created_at = :old WHERE project_id = :p AND version < :v"
        ), {"old": old, "p": tree.pid, "v": versions[-1]})  # fmt: skip
        deleted = await changes.purge(db)
        left = (await db.scalars(select(ChangeLog.version).where(
            ChangeLog.project_id == tree.pid).order_by(ChangeLog.version))).all()  # fmt: skip
    assert deleted >= len(versions) - 2
    assert left == versions[-2:]  # граница хранения + свежая запись

    since = versions[0]
    rest = await stage.rest("GET", tree.expert_b, f"/projects/{tree.pid}/changes",
                            params={"since": since})  # fmt: skip
    assert rest.status_code == 410
    b = await stage.connect(tree.expert_b)
    reply = await b.subscribe(tree.pid, since=since)
    assert reply["result"]["resync"] is True
    assert (await b.event("resync.required"))["data"]["project_id"] == str(tree.pid)
    # граница сама по себе отдаётся: клиент на её предыдущей версии догоняет без перезагрузки
    ok = await stage.rest("GET", tree.expert_b, f"/projects/{tree.pid}/changes",
                          params={"since": versions[-2] - 1})  # fmt: skip
    assert ok.status_code == 200
    assert [e["project_version"] for e in ok.json()["events"]] == versions[-2:]
