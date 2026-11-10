"""SEC-010: отказы и превышения лимитов пишутся в аудит не чаще раза в минуту на ключ.

SEC-AUD-01 («Безопасность»), SEC-AUTHZ-03, FR-SA-06, SEC-WEB-07. Поток отказов не должен
раздувать журнал: 100 отказов за минуту — одна запись; число свёрнутых повторов уходит в
``suppressed`` следующей записи ``security.access_denied``.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.security.audit import security_events
from estimator.security.ratelimit.limiter import LIMITS, Limit
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-01")]


async def _rows(db: AsyncSession, event: str, **where: str) -> list[dict[str, Any]]:
    sql = "SELECT details, user_id, ip, login FROM audit.audit_log WHERE event_type = :e"
    params: dict[str, Any] = {"e": event}
    for i, (column, value) in enumerate(where.items()):
        sql += f" AND {column} = :v{i}"
        params[f"v{i}"] = value
    rows = await db.execute(text(sql + " ORDER BY id"), params)
    return [
        {"details": r[0], "user_id": r[1], "ip": str(r[2]) if r[2] else None, "login": r[3]}
        for r in rows.all()
    ]


async def _deny(db: AsyncSession, redis: Redis, user: uuid.UUID, project: uuid.UUID) -> bool:
    return await security_events.access_denied(
        db, redis, user_id=user, login="t", ip="10.0.0.1", session_id=None, project_id=project,
        status=404, permission="tree.read", method="GET", route="/projects/{id}/tree",
    )  # fmt: skip


@pytest.mark.spec("SEC-AUTHZ-03")
async def test_hundred_denials_in_a_minute_give_one_record(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    user, project = uuid.uuid4(), uuid.uuid4()
    written = [await _deny(db_session, redis_client, user, project) for _ in range(100)]
    assert written.count(True) == 1
    rows = await _rows(db_session, "security.access_denied", object_id=str(project))
    assert len(rows) == 1
    assert rows[0]["details"]["suppressed"] == 0

    # Окно истекло: следующая запись несёт число свёрнутых повторов
    await redis_client.delete(f"{security_events.KEY_PREFIX}denied:{user}:{project}:tree.read")
    assert await _deny(db_session, redis_client, user, project)
    rows = await _rows(db_session, "security.access_denied", object_id=str(project))
    assert [r["details"]["suppressed"] for r in rows] == [0, 99]

    other = uuid.uuid4()  # другой объект — свой ключ
    assert await _deny(db_session, redis_client, user, other)


async def test_network_denials_are_throttled_per_user_and_route(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    user = uuid.uuid4()
    ip = f"192.0.2.{uuid.uuid4().int % 250 + 1}"
    await redis_client.delete(f"{security_events.KEY_PREFIX}network:ip:{ip}:/system/health")

    async def deny(route: str, who: uuid.UUID | None = user) -> bool:
        return await security_events.network_denied(
            db_session, redis_client, user_id=who, login=None, ip=ip, session_id=None,
            route=route,
        )  # fmt: skip

    assert [await deny("/system/health") for _ in range(50)].count(True) == 1
    assert await deny("/system/settings/{section}"), "другой путь — своя запись"
    assert await deny("/system/health", None), "без сессии ключ — IP"
    rows = await _rows(db_session, "security.network_denied", ip=ip)
    assert [r["details"]["route"] for r in rows] == [
        "/system/health", "/system/settings/{section}", "/system/health",
    ]  # fmt: skip


async def test_redis_failure_still_writes(db_session: AsyncSession) -> None:
    class Broken:
        async def set(self, *_: Any, **__: Any) -> None:
            raise ConnectionError("redis down")

    project = uuid.uuid4()
    assert await _deny(db_session, Broken(), uuid.uuid4(), project)  # type: ignore[arg-type]
    assert len(await _rows(db_session, "security.access_denied", object_id=str(project))) == 1


@pytest.mark.spec("SEC-WEB-07")
async def test_mutation_limit_is_audited_once(
    api: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(LIMITS, "mutations", Limit("mutations", 2, 60))
    await complete_setup(db_session)
    await set_setting(db_session, "security.mfa_policy", {"user": "optional"})
    user = await make_user(db_session)
    login = await api.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
    assert login.status_code == 200, login.text
    url = "/api/v1/me/notification-settings"
    body = {"notify_digest": True, "notify_questions": False}
    codes = [
        (await api.put(url, json=body, headers=csrf_headers(api))).status_code for _ in range(6)
    ]
    assert codes == [200, 200, 429, 429, 429, 429]
    rows = await _rows(db_session, "security.rate_limited", user_id=str(user.id))
    assert len(rows) == 1
    assert rows[0]["details"]["limit"] == "mutations"
    assert 1 <= rows[0]["details"]["retry_after"] <= 60
    assert rows[0]["login"] == user.login


@pytest.mark.spec("SEC-WEB-07")
async def test_ip_limit_is_audited_without_user(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    allowed = LIMITS["auth_options"].max_hits  # лимит зависимости берётся при импорте маршрута
    codes = [(await api.get("/api/v1/auth/options")).status_code for _ in range(allowed + 4)]
    assert codes == [200] * allowed + [429] * 4
    rows = [r for r in await _rows(db_session, "security.rate_limited")
            if r["details"]["limit"] == "auth_options"]  # fmt: skip
    assert len(rows) == 1
    assert rows[0]["user_id"] is None
    assert str(rows[0]["ip"]).startswith("10.")


@pytest.mark.spec("FR-LOCK-02")
async def test_login_ip_limit_is_a_security_event(
    api: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(LIMITS, "login_ip", Limit("login_ip", 2, 60, block_seconds=300))
    await complete_setup(db_session)
    body = {"login": f"nobody-{uuid.uuid4().hex[:6]}", "password": "wrong-password"}
    codes = [(await api.post("/api/v1/auth/login", json=body)).status_code for _ in range(5)]
    assert codes == [401, 401, 429, 429, 429]
    rows = await _rows(db_session, "security.rate_limited", login=body["login"])
    assert len(rows) == 1
    assert rows[0]["details"]["limit"] == "login_ip"
    assert rows[0]["user_id"] is None


async def test_project_limit_points_to_project(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    project = uuid.uuid4()
    for _ in range(3):
        await security_events.rate_limited(
            db_session, redis_client, "remind", str(project), 3600,
            user_id=uuid.uuid4(), project_id=project,
        )  # fmt: skip
    rows = await _rows(db_session, "security.rate_limited", object_id=str(project))
    assert [r["details"] for r in rows] == [{"limit": "remind", "retry_after": 3600,
                                             "project_id": str(project)}]  # fmt: skip
