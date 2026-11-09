"""RT-003, RT-004, RT-006, RT-008 на живом сервере: подключение, подписки, фильтр, отзыв.

SPEC 15.4, 13.3, SEC-AUTHZ-01/04, SEC-WEB-04/08, FR-SA-06, FR-SESS-02/05, TC-AUTH-05, G-13.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import delete, select, text
from websockets.exceptions import InvalidStatus

from estimator.auth.sessions import RevokeReason, id_hash
from estimator.db.enums import ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.projects import ProjectMember
from estimator.realtime.bus import build_event, deliver
from estimator.realtime.bus.memory import validate_event
from tests.integration.auth.conftest import set_setting
from tests.integration.rt.conftest import Stage

pytestmark = [pytest.mark.integration, pytest.mark.spec("15.4")]


def _money(project_id: uuid.UUID) -> dict:
    return build_event(
        f"project:{project_id}:money", "money.updated",
        {"totals": {"cost_rub": "100", "quote_rub": "120", "quote_cur": "120"}},
        project_version=5,
    )  # fmt: skip


def _updated(project_id: uuid.UUID, version: int) -> dict:
    return build_event(f"project:{project_id}", "project.updated",
                       {"changes": {"name": "Новое имя"}, "author": None},
                       project_version=version)  # fmt: skip


def _presence_ids(message: dict) -> set[str]:
    return {u["id"] for u in message["data"]["users"]}


@pytest.mark.spec("SEC-AUTHZ-01")
async def test_handshake_needs_session(stage: Stage) -> None:
    with pytest.raises(InvalidStatus) as exc:
        await stage.connect(None)
    assert exc.value.response.status_code == 401
    with pytest.raises(InvalidStatus) as exc:
        await stage.connect("no-such-session")
    assert exc.value.response.status_code == 401


@pytest.mark.spec("SEC-WEB-04")
async def test_foreign_origin_is_closed_4403(stage: Stage) -> None:
    _, sid = await stage.user()
    for origin in ("https://evil.example", None, "http://localhost"):
        client = await stage.connect(sid, origin=origin)
        assert await client.closed() == 4403


@pytest.mark.spec("FR-SA-06")
async def test_superadmin_from_foreign_network_is_404(stage: Stage) -> None:
    async with stage.data() as db:
        await set_setting(db, "security.admin_networks", ["10.9.0.0/16"])
    _, sid = await stage.user(SystemRole.SUPERADMIN)
    with pytest.raises(InvalidStatus) as exc:
        await stage.connect(sid, ip="10.1.2.3")
    assert exc.value.response.status_code == 404
    client = await stage.connect(sid, ip="10.9.1.1")
    await client.call("heartbeat")
    async with stage.data() as db:
        count = await db.scalar(text(
            "SELECT count(*) FROM audit.audit_log WHERE event_type = 'security.network_denied'"
        ))  # fmt: skip
    assert count == 1


@pytest.mark.spec("SEC-AUTHZ-04")
async def test_expert_gets_no_money_channel(stage: Stage) -> None:
    project = await stage.project()
    backend = await stage.discipline()
    _, expert = await stage.user(member=(project, ProjectRole.EXPERT, backend))
    _, moderator = await stage.user(
        SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None)
    )
    _, no_totp = await stage.user(
        SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None), mfa=False
    )
    base = f"project:{project.id}"
    e = await stage.connect(expert)
    reply = await e.subscribe(project.id, since=0)
    validate_reply(reply)
    assert reply["type"] == "ack"
    assert reply["result"] == {"project_version": 0, "channels": [base], "resync": False}
    m = await stage.connect(moderator)
    assert (await m.subscribe(project.id))["result"]["channels"] == [
        base, f"{base}:money", f"{base}:notes",
    ]  # fmt: skip
    n = await stage.connect(no_totp)
    assert (await n.subscribe(project.id))["result"]["channels"] == [base]

    # RT-004: событие из шины (Redis) — всем подписчикам канала, деньги — только в :money
    await deliver(_money(project.id))
    await deliver(_updated(project.id, 6))
    assert (await m.event("money.updated"))["data"]["totals"]["cost_rub"] == "100"
    for client in (e, m, n):
        assert (await client.event("project.updated"))["project_version"] == 6
    assert not e.events("money.updated")
    assert not n.events("money.updated")


@pytest.mark.spec("SEC-AUTHZ-03")
async def test_foreign_and_missing_project_look_the_same(stage: Stage) -> None:
    project = await stage.project()
    other = await stage.project()
    hidden = await stage.project(ProjectStatus.PREPARATION)
    backend = await stage.discipline()
    _, sid = await stage.user(member=(other, ProjectRole.EXPERT, backend))
    async with stage.data() as db:
        db.add(ProjectMember(project_id=hidden.id, user_id=(await db.scalar(
            select(ProjectMember.user_id).where(ProjectMember.project_id == other.id)
        )), role=ProjectRole.EXPERT, discipline_id=backend))  # fmt: skip
    client = await stage.connect(sid)
    for target in (project.id, uuid.uuid4(), hidden.id):
        reply = await client.subscribe(target)
        validate_reply(reply)
        assert (reply["type"], reply["code"]) == ("error", "NOT_FOUND")
        assert reply["op"] == "subscribe"
    async with stage.data() as db:
        rows = (await db.execute(text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'security.access_denied'"
        ))).scalars().all()  # fmt: skip
    assert rows
    assert rows[0]["method"] == "WS"


async def test_bad_commands_and_limits(stage: Stage) -> None:
    _, sid = await stage.user()
    client = await stage.connect(sid)
    await client.send("не json")
    reply = await client.wait(lambda m: m.get("type") == "error")
    assert reply["code"] == "VALIDATION_FAILED"
    bad = await client.call("subscribe", project_id="nope")
    assert (bad["code"], bad["op"]) == ("VALIDATION_FAILED", "subscribe")
    extra = await client.call("unsubscribe", project_id=str(uuid.uuid4()), since=1)
    assert extra["code"] == "VALIDATION_FAILED"
    locked = await client.call("lock", project_id=str(uuid.uuid4()), node_id=str(uuid.uuid4()),
                               field="r")  # fmt: skip
    assert locked["code"] == "NOT_FOUND"  # не подписан на проект
    await client.send("x" * (64 * 1024 + 1))
    assert await client.closed() == 1009


@pytest.mark.spec("FR-SESS-02")
@pytest.mark.tc("TC-AUTH-05")
async def test_heartbeat_does_not_extend_session_and_idle_closes_ws(stage: Stage) -> None:
    project = await stage.project()
    user_id, sid = await stage.user(member=(project, ProjectRole.MODERATOR, None))
    client = await stage.connect(sid)
    await client.subscribe(project.id)
    seen = (await stage.service.load(sid)).record.last_seen_at  # type: ignore[union-attr]
    stage.clock.now += 30 * 60  # type: ignore[attr-defined]
    beat = await client.call("heartbeat", locks=[])
    assert beat["result"] == {"extended": [], "lost": []}
    assert (await stage.service.load(sid)).record.last_seen_at == seen  # type: ignore[union-attr]

    stage.clock.now += 31 * 60  # type: ignore[attr-defined]  # бездействие 60 мин истекло
    started = time.monotonic()
    ended = await client.event("session.ended")
    assert ended["channel"] == f"user:{user_id}"
    assert ended["data"] == {"reason": "idle_timeout"}
    assert await client.closed() == 4401
    assert time.monotonic() - started < 5


@pytest.mark.spec("FR-SESS-05")
async def test_revoked_session_closes_ws_on_every_tab(stage: Stage) -> None:
    user_id, sid = await stage.user()
    first, second = await stage.connect(sid), await stage.connect(sid)
    await first.call("heartbeat")
    await second.call("heartbeat")
    async with stage.data() as db:
        await stage.service.revoke_user(db, user_id, RevokeReason.PASSWORD_CHANGED)
    # хук after-commit транзакции теста не сработает: выполнить его как после COMMIT
    realtime = stage.realtime
    assert realtime is not None
    from estimator.auth.sessions import SessionEnded

    await realtime.on_session_ended(SessionEnded(user_id, id_hash(sid), "password_changed"))
    for client in (first, second):
        assert (await client.event("session.ended"))["data"] == {"reason": "password_changed"}
        assert await client.closed() == 4401


@pytest.mark.gherkin("G-13")
@pytest.mark.spec("FR-SESS-05")
async def test_removed_member_gets_access_revoked_within_5s(stage: Stage) -> None:
    project = await stage.project()
    backend = await stage.discipline()
    expert_id, expert = await stage.user(member=(project, ProjectRole.EXPERT, backend))
    _, moderator = await stage.user(
        SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None)
    )
    e, m = await stage.connect(expert), await stage.connect(moderator)
    await e.subscribe(project.id)
    await m.subscribe(project.id)
    await m.wait(lambda x: x.get("event") == "presence" and len(x["data"]["users"]) == 2)

    async with stage.data() as db:
        await db.execute(delete(ProjectMember).where(ProjectMember.user_id == expert_id))
    started = time.monotonic()
    revoked = await e.event("access.revoked")
    assert time.monotonic() - started < 5
    assert revoked["data"] == {"project_id": str(project.id), "reason": "removed_from_team"}
    # отписан: события проекта больше не приходят, а модератор видит его уход из присутствия
    gone = await m.wait(lambda x: x.get("event") == "presence" and len(x["data"]["users"]) == 1)
    assert str(expert_id) not in _presence_ids(gone)
    await deliver(_updated(project.id, 9))
    await m.event("project.updated")
    beat = await e.call("heartbeat")
    assert beat["type"] == "ack"
    assert not e.events("project.updated")


async def test_member_updated_triggers_immediate_recheck(stage: Stage) -> None:
    project = await stage.project()
    expert_id, expert = await stage.user(
        member=(project, ProjectRole.EXPERT, await stage.discipline())
    )
    realtime = stage.realtime
    assert realtime is not None
    realtime.revalidate_seconds = 60  # только по событию
    e = await stage.connect(expert)
    await e.subscribe(project.id)
    async with stage.data() as db:
        await db.execute(delete(ProjectMember).where(ProjectMember.user_id == expert_id))
    await deliver(build_event(f"project:{project.id}", "member.updated",
                              {"user_ids": [str(expert_id)], "change": "removed"},
                              project_version=3))  # fmt: skip
    assert (await e.event("access.revoked", within=3))["data"]["reason"] == "removed_from_team"


@pytest.mark.spec("11.4")
async def test_presence_two_clients_see_each_other(stage: Stage) -> None:
    project = await stage.project()
    backend = await stage.discipline()
    a_id, a_sid = await stage.user(member=(project, ProjectRole.EXPERT, backend))
    b_id, b_sid = await stage.user(member=(project, ProjectRole.EXPERT, backend))
    a = await stage.connect(a_sid)
    await a.subscribe(project.id)
    b = await stage.connect(b_sid)
    await b.subscribe(project.id)
    both = {str(a_id), str(b_id)}
    seen_by_a = await a.wait(lambda m: m.get("event") == "presence" and _presence_ids(m) == both)
    validate_event(seen_by_a)
    user = next(u for u in seen_by_a["data"]["users"] if u["id"] == str(b_id))
    assert user["color"].startswith("#")
    assert len(user["initials"]) == 2
    await b.wait(lambda m: m.get("event") == "presence" and _presence_ids(m) == both)

    await b.conn.close()
    left = await a.wait(lambda m: m.get("event") == "presence" and _presence_ids(m) == {str(a_id)})
    assert left["channel"] == f"project:{project.id}"


def validate_reply(reply: dict) -> None:
    """Ответ сервера по ``$defs.ServerReply`` контракта RT-001."""
    from jsonschema import Draft202012Validator

    from estimator.realtime.bus.contract import schema

    doc = schema()
    validator = Draft202012Validator({"$ref": "#/$defs/ServerReply", "$defs": doc["$defs"]})
    errors = list(validator.iter_errors(reply))
    assert not errors, [e.message for e in errors]


async def test_command_flood_is_limited_then_closed(
    stage: Stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from estimator.realtime import ws

    monkeypatch.setattr(ws, "RATE_MAX_COMMANDS", 3)
    _, sid = await stage.user()
    client = await stage.connect(sid)
    for _ in range(3):
        assert (await client.call("heartbeat"))["type"] == "ack"
    limited = await client.call("heartbeat")
    validate_reply(limited)
    assert limited["code"] == "RATE_LIMITED"
    assert limited["retry_after"] >= 1
    for _ in range(3):
        await client.send({"op": "heartbeat"})
    assert await client.closed() == 4429


async def test_restricted_session_cannot_open_ws(stage: Stage) -> None:
    from estimator.auth.policy import SessionPolicy
    from tests.integration.auth.helpers import make_user

    async with stage.data() as db:
        user = await make_user(db)
        sid, _ = await stage.service.create(db, user.id, [], SessionPolicy(), ip="10.1.2.3",
                                            password_change_required=True)  # fmt: skip
        enroll, _ = await stage.service.create(db, user.id, [], SessionPolicy(), ip="10.1.2.3",
                                               enrollment_required=True)  # fmt: skip
    for session in (sid, enroll):
        with pytest.raises(InvalidStatus) as exc:
            await stage.connect(session)
        assert exc.value.response.status_code == 403
    async with stage.data() as db:
        await db.execute(text("DELETE FROM system_settings WHERE key = 'app.setup'"))
    _, plain = await stage.user()
    with pytest.raises(InvalidStatus) as exc:
        await stage.connect(plain)
    assert exc.value.response.status_code == 503


async def test_project_moved_to_preparation_hides_it_from_expert(stage: Stage) -> None:
    project = await stage.project()
    _, expert = await stage.user(member=(project, ProjectRole.EXPERT, await stage.discipline()))
    _, moderator = await stage.user(
        SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None)
    )
    e, m = await stage.connect(expert), await stage.connect(moderator)
    await e.subscribe(project.id)
    await m.subscribe(project.id)
    async with stage.data() as db:
        await db.execute(
            text("UPDATE projects SET status = 'preparation' WHERE id = :id"), {"id": project.id}
        )
    assert (await e.event("access.revoked"))["data"]["reason"] == "project_hidden"
    await deliver(_updated(project.id, 2))
    await m.event("project.updated")
    assert not m.events("access.revoked")
