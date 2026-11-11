"""QA-011 · TC-CONC-01…04 на двух настоящих процессах API за общим Redis (SPEC 13.2–13.3).

Пользователи работают через разные реплики, как за Nginx: REST и WebSocket к процессу 1 и
процессу 2. Данные — в отдельной базе с миграциями (процессы Uvicorn фиксируют транзакции сами).

* TC-CONC-01: разные поля одного листа с одной базовой версией — обе правки применены;
* TC-CONC-02: одно поле с одной базовой версией — второму 409 с текущим значением;
* TC-CONC-03: клиент процесса 2 пропустил 100 правок процесса 1 и догнал их подпиской с
  ``since`` — дерево совпадает с серверным;
* TC-CONC-04: захват ячейки на процессе 1 — PATCH другого через процесс 2 получает 423,
  модератор перехватывает, закрытие WebSocket снимает захват.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import COOKIE_NAME, SessionService
from estimator.db.enums import NodeKind, SystemRole
from estimator.db.models.dictionaries import Discipline, Phase
from estimator.db.models.tree import Node
from estimator.security.web.csrf import CSRF_HEADER
from tests.conftest import REDIS_ENV_VAR
from tests.integration.auth.conftest import complete_setup
from tests.integration.auth.helpers import make_user
from tests.integration.rt.conftest import Client
from tests.integration.rt.test_two_processes import live_database_url, live_db
from tests.plugins.processes import ApiProcess, StartApi, WsConnect

__all__ = ["live_database_url", "live_db"]

pytestmark = [pytest.mark.integration, pytest.mark.spec("13.3"), pytest.mark.spec("FR-TREE-31"),
              pytest.mark.spec("FR-TREE-32"), pytest.mark.spec("FR-TREE-33")]  # fmt: skip

ORIGIN = "https://localhost"
MISSED = 100


@dataclass
class Session:
    user_id: uuid.UUID
    sid: str
    csrf: str


@dataclass
class World2:
    first: ApiProcess
    second: ApiProcess
    moderator: Session
    a: Session
    b: Session
    pid: uuid.UUID
    leaf: uuid.UUID
    ws: WsConnect

    async def rest(
        self, api: ApiProcess, who: Session, method: str, path: str, **kw: Any
    ) -> httpx.Response:
        headers = {"Cookie": f"{COOKIE_NAME}={who.sid}", CSRF_HEADER: who.csrf, "Origin": ORIGIN}
        async with httpx.AsyncClient(base_url=api.base_url, timeout=10) as client:
            return await client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def client(self, api: ApiProcess, who: Session, **sub: Any) -> Client:
        headers = {"Cookie": f"{COOKIE_NAME}={who.sid}", "Origin": ORIGIN}
        conn = await self.ws(f"{api.ws_base_url}/api/v1/ws", headers=headers)
        client = Client(conn)
        reply = await client.subscribe(self.pid, **sub)
        assert reply["type"] == "ack", reply
        return client

    async def node(self, api: ApiProcess, who: Session) -> dict[str, Any]:
        got = await self.rest(api, who, "GET", f"/projects/{self.pid}/tree")
        assert got.status_code == 200, got.text
        return next(n for n in got.json()["nodes"] if n["id"] == str(self.leaf))

    async def patch(
        self, api: ApiProcess, who: Session, base: int, **changes: Any
    ) -> httpx.Response:
        return await self.rest(api, who, "PATCH", f"/nodes/{self.leaf}",
                               json={"base_version": base, "changes": changes})  # fmt: skip


async def _session(db: AsyncSession, service: SessionService, *roles: SystemRole) -> Session:
    user = await make_user(db, *roles)
    sid, record = await service.create(db, user.id, roles, SessionPolicy(), ip="10.0.0.1",
                                       mfa_passed=True)  # fmt: skip
    return Session(user.id, sid, record.csrf)


@pytest.fixture
async def world2(
    live_database_url: str,
    live_db: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    api_processes: StartApi,
    ws_connect: WsConnect,
) -> World2:
    service = SessionService(redis_client)
    async with live_db() as db, db.begin():
        await complete_setup(db)
        moderator = await _session(db, service, SystemRole.MODERATOR)
        a = await _session(db, service)
        b = await _session(db, service)
        phase = (await db.scalars(select(Phase.id).where(Phase.name == "Разработка"))).one()
        backend = (await db.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))).one()
    env = {"DATABASE_URL": live_database_url, "REDIS_URL": os.environ[REDIS_ENV_VAR],
           "FORWARDED_ALLOW_IPS": "127.0.0.1"}  # fmt: skip
    first, second = api_processes(2, env=env)
    w = World2(first, second, moderator, a, b, uuid.uuid4(), uuid.uuid4(), ws_connect)
    created = await w.rest(first, moderator, "POST", "/projects", json={
        "name": "Портал дилеров", "customer": "ООО Ромашка", "phase_ids": [str(phase)],
    })  # fmt: skip
    assert created.status_code == 201, created.text
    w.pid = uuid.UUID(created.json()["project"]["id"])
    added = await w.rest(first, moderator, "POST", f"/projects/{w.pid}/disciplines",
                         json={"discipline_id": str(backend)})  # fmt: skip
    assert added.status_code == 201, added.text
    team = await w.rest(first, moderator, "PUT", f"/projects/{w.pid}/members", json={"members": [
        {"user_id": str(moderator.user_id), "role": "moderator"},
        {"user_id": str(a.user_id), "role": "expert", "discipline_id": str(backend)},
        {"user_id": str(b.user_id), "role": "expert", "discipline_id": str(backend)},
    ]})  # fmt: skip
    assert team.status_code == 200, team.text
    launched = await w.rest(first, moderator, "POST", f"/projects/{w.pid}/status",
                            json={"to": "estimation"})  # fmt: skip
    assert launched.status_code == 200, launched.text
    async with live_db() as db:
        branch = (await db.scalars(select(Node.id).where(
            Node.project_id == w.pid, Node.discipline_id == backend,
            Node.kind == NodeKind.DISCIPLINE,
        ))).first()  # fmt: skip
    leaf = await w.rest(first, a, "POST", f"/projects/{w.pid}/nodes",
                        json={"parent_id": str(branch), "title": "Авторизация", "o": "4", "r": "8",
                              "p": "12"})  # fmt: skip
    assert leaf.status_code == 201, leaf.text
    w.leaf = uuid.UUID(leaf.json()["node"]["id"])
    return w


@pytest.mark.tc("TC-CONC-01")
@pytest.mark.tc("TC-CONC-02")
async def test_field_merge_and_conflict_across_processes(world2: World2) -> None:
    w = world2
    base = (await w.node(w.first, w.a))["version"]
    one = await w.patch(w.first, w.a, base, o="5")
    two = await w.patch(w.second, w.b, base, p="13")  # то же base, другое поле
    assert (one.status_code, two.status_code) == (200, 200), (one.text, two.text)
    node = await w.node(w.second, w.a)
    assert (node["o"], node["r"], node["p"]) == ("5", "8", "13")

    base = node["version"]
    first = await w.patch(w.first, w.a, base, r="10")
    clash = await w.patch(w.second, w.b, base, r="11")
    assert first.status_code == 200, first.text
    assert clash.status_code == 409, clash.text
    body = clash.json()
    assert body["code"] == "FIELD_CONFLICT", body
    assert "10" in str(body), body  # текущее значение поля — в ответе
    assert (await w.node(w.first, w.b))["r"] == "10"


@pytest.mark.tc("TC-CONC-03")
async def test_reconnect_after_100_missed_changes(world2: World2) -> None:
    w = world2
    tree = await w.rest(w.second, w.b, "GET", f"/projects/{w.pid}/tree")
    since = tree.json()["project_version"]
    b = await w.client(w.second, w.b, since=since)
    await b.conn.close()  # разрыв
    for i in range(MISSED):
        node = await w.node(w.first, w.a)
        done = await w.patch(w.first, w.a, node["version"], r=str(20 + i))
        assert done.status_code == 200, done.text
    b = await w.client(w.second, w.b, since=since)
    caught = [await b.event("node.updated", within=10) for _ in range(MISSED)]
    assert caught[-1]["data"]["node"]["r"] == str(20 + MISSED - 1)
    versions = [e["project_version"] for e in caught]
    assert versions == sorted(versions)
    server = await w.node(w.first, w.a)
    assert {k: caught[-1]["data"]["node"][k] for k in ("o", "r", "p")} == {
        k: server[k] for k in ("o", "r", "p")
    }


@pytest.mark.tc("TC-CONC-04")
async def test_cell_lock_across_processes(world2: World2) -> None:
    w = world2
    args = {"project_id": str(w.pid), "node_id": str(w.leaf), "field": "r"}
    a = await w.client(w.first, w.a)
    b = await w.client(w.second, w.b)
    assert (await a.call("lock", **args))["type"] == "ack"
    assert (await b.event("cell.locked"))["data"]["user"]["id"] == str(w.a.user_id)

    base = (await w.node(w.second, w.b))["version"]
    rejected = await w.patch(w.second, w.b, base, r="18")
    assert (rejected.status_code, rejected.json()["code"]) == (423, "CELL_LOCKED"), rejected.text
    assert rejected.json()["locked_by"]["id"] == str(w.a.user_id)

    m = await w.client(w.second, w.moderator)
    assert (await m.call("lock", **args, force=True))["type"] == "ack"
    forced = await a.wait(lambda x: x.get("event") == "cell.unlocked")
    assert forced["data"]["reason"] == "forced"
    assert (await m.call("unlock", **args))["type"] == "ack"

    assert (await a.call("lock", **args))["type"] == "ack"
    await b.wait(lambda x: x.get("event") == "cell.locked" and x["data"]["user"]["id"]
                 == str(w.a.user_id))  # fmt: skip
    await a.conn.close()
    gone = await b.wait(lambda x: x.get("event") == "cell.unlocked"
                        and x["data"]["reason"] == "disconnected", within=10)  # fmt: skip
    assert gone["data"]["field"] == "r"
    saved = await w.patch(w.second, w.b, (await w.node(w.second, w.b))["version"], r="18")
    assert saved.status_code == 200, saved.text
