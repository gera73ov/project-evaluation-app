"""RT-003/RT-004 без сети: разбор команд, ответы по контракту, раздача событий по правам."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from estimator.realtime.bus import build_event
from estimator.realtime.bus.contract import schema
from estimator.realtime.revoke import ended_reason, session_ended_message
from estimator.realtime.users import MUTED, PALETTE, initials, user_color, user_ref
from estimator.realtime.ws import hub as hub_mod
from estimator.realtime.ws import protocol
from estimator.realtime.ws.hub import Connection, Hub, ProjectAccess

pytestmark = [pytest.mark.spec("15.4")]

PROJECT = uuid.uuid4()
NODE = str(uuid.uuid4())


def _reply_errors(reply: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator({"$ref": "#/$defs/ServerReply", "$defs": schema()["$defs"]})
    return [e.message for e in validator.iter_errors(reply)]


def _command_errors(command: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator({"$ref": "#/$defs/ClientCommand", "$defs": schema()["$defs"]})
    return [e.message for e in validator.iter_errors(command)]


VALID = [
    {"op": "subscribe", "project_id": str(PROJECT), "since": 10, "req_id": "1"},
    {"op": "subscribe", "project_id": str(PROJECT)},
    {"op": "unsubscribe", "project_id": str(PROJECT)},
    {"op": "lock", "project_id": str(PROJECT), "node_id": NODE, "field": "r", "force": True},
    {"op": "unlock", "project_id": str(PROJECT), "node_id": NODE, "field": "title"},
    {"op": "heartbeat", "locks": [{"node_id": NODE, "field": "o"}]},
    {"op": "heartbeat"},
]
INVALID = [
    "[]",
    "{",
    {"op": "dance"},
    {"op": "subscribe"},
    {"op": "subscribe", "project_id": "x"},
    {"op": "subscribe", "project_id": str(PROJECT), "since": -1},
    {"op": "subscribe", "project_id": str(PROJECT), "since": True},
    {"op": "subscribe", "project_id": str(PROJECT), "extra": 1},
    {"op": "lock", "project_id": str(PROJECT), "node_id": NODE, "field": "rate"},
    {"op": "lock", "project_id": str(PROJECT), "node_id": NODE, "field": "r", "force": "yes"},
    {"op": "heartbeat", "locks": [{"node_id": NODE}]},
    {"op": "heartbeat", "locks": [{"node_id": NODE, "field": "r"}] * 21},
    {"op": "heartbeat", "locks": "all"},
    {"op": "heartbeat", "req_id": "x" * 65},
]


@pytest.mark.parametrize("command", VALID)
def test_valid_commands_match_contract(command: dict[str, Any]) -> None:
    assert not _command_errors(command)
    parsed = protocol.parse_command(json.dumps(command))
    assert parsed.op == command["op"]
    assert parsed.req_id == command.get("req_id")


@pytest.mark.parametrize("command", INVALID)
def test_invalid_commands_are_rejected(command: dict[str, Any] | str) -> None:
    raw = command if isinstance(command, str) else json.dumps(command)
    with pytest.raises(protocol.CommandError) as exc:
        protocol.parse_command(raw)
    assert exc.value.code == "VALIDATION_FAILED"
    reply = protocol.command_error(exc.value)
    assert not _reply_errors(reply)
    if isinstance(command, dict) and isinstance(command.get("op"), str):
        assert reply.get("op") == command["op"]


def test_replies_match_contract() -> None:
    assert not _reply_errors(protocol.ack("subscribe", "1", {"project_version": 1}))
    assert not _reply_errors(protocol.ack("unsubscribe", None))
    locked = protocol.error("lock", "2", "CELL_LOCKED", "занято",
                            locked_by=user_ref(uuid.uuid4(), "Иванов Иван"),
                            expires_at="2026-11-09T10:00:00Z", junk=1)  # fmt: skip
    assert not _reply_errors(locked)
    assert "junk" not in locked
    assert protocol.error(None, None, "RATE_LIMITED", retry_after=3) == {
        "type": "error", "code": "RATE_LIMITED", "retry_after": 3,
    }  # fmt: skip


def test_user_ref() -> None:
    uid = uuid.UUID(int=13)
    assert initials("Иванов Иван Иванович") == "ИИ"
    assert initials("Суперадмин") == "С"
    assert initials("") == ""
    assert user_color(uid) == PALETTE[3]
    assert user_color(uid, active=False) == MUTED
    ref = user_ref(uid, "Смирнова Анна")
    assert ref == {"id": str(uid), "full_name": "Смирнова Анна", "initials": "СА",
                   "is_active": True, "color": PALETTE[3]}  # fmt: skip


def test_session_end_reasons() -> None:
    assert ended_reason("logout") == "logged_out"
    assert ended_reason("blocked") == "user_blocked"
    assert ended_reason("mode_switch") == "auth_mode_switched"
    assert ended_reason("что-то новое") == "revoked"
    from estimator.auth.sessions import SessionEnded

    uid = uuid.uuid4()
    msg = session_ended_message(SessionEnded(uid, b"\x01\x02", "password_changed"))
    assert msg == {"kind": "session_ended", "user_id": str(uid), "session_hash": "0102",
                   "reason": "password_changed"}  # fmt: skip


def _conn(**over: Any) -> Connection:
    return Connection(user_id=uuid.uuid4(), session_id="s", session_hash=b"h", **over)


def _drain(conn: Connection) -> list[dict[str, Any]]:
    out = []
    while not conn.queue.empty():
        item = conn.queue.get_nowait()
        if item is not None:
            out.append(item)
    return out


@pytest.mark.spec("SEC-AUTHZ-04")
def test_hub_routes_by_channel_and_current_rights() -> None:
    hub = Hub(strict=True)
    expert, moderator, stranger = _conn(), _conn(), _conn()
    for c in (expert, moderator, stranger):
        hub.add(c)
    hub.set_access(expert, ProjectAccess(PROJECT))
    hub.set_access(moderator, ProjectAccess(PROJECT, money=True, notes=True))
    base = f"project:{PROJECT}"
    money = build_event(f"{base}:money", "money.updated",
                        {"totals": {"cost_rub": "1", "quote_rub": "1", "quote_cur": "1"}},
                        project_version=1)  # fmt: skip
    updated = build_event(base, "project.updated", {"changes": {}, "author": None},
                          project_version=2)  # fmt: skip
    personal = build_event(stranger.user_channel, "session.ended", {"reason": "revoked"})
    assert hub.dispatch(money) == 1
    assert hub.dispatch(updated) == 2
    assert hub.dispatch(personal) == 1
    assert [m["event"] for m in _drain(moderator)] == ["money.updated", "project.updated"]
    assert [m["event"] for m in _drain(expert)] == ["project.updated"]
    assert [m["event"] for m in _drain(stranger)] == ["session.ended"]

    # права пересчитаны: модератор потерял TOTP — канал :money снят без отписки от проекта
    hub.set_access(moderator, ProjectAccess(PROJECT))
    assert hub.dispatch(money) == 0
    assert hub.subscribers(f"{base}:money") == frozenset()
    assert hub.drop_project(expert, PROJECT)
    assert not hub.drop_project(expert, PROJECT)
    assert hub.dispatch(updated) == 1
    assert hub.in_project(PROJECT) == [moderator]
    assert hub.projects() == {PROJECT}
    assert hub.by_session(b"h")
    assert hub.by_user(stranger.user_id) == [stranger]
    hub.remove(moderator)
    assert hub.dispatch(updated) == 0


def test_hub_blocks_money_leak_in_strict_mode_and_custom_filters() -> None:
    hub = Hub(strict=True)
    conn = _conn()
    hub.add(conn)
    hub.set_access(conn, ProjectAccess(PROJECT, sources=frozenset({"expert"})))
    # событие в обход шины (шина такое не пропускает) с денежным ключом
    leak = {"type": "event", "event": "project.updated", "channel": f"project:{PROJECT}",
            "ts": "2026-11-09T00:00:00.000Z", "project_version": 1,
            "data": {"changes": {"rate": "3000"}, "author": None}}  # fmt: skip
    assert hub.dispatch(leak) == 0
    assert Hub(strict=False).dispatch(leak) == 0  # нет подписчиков

    scanned = build_event(f"project:{PROJECT}", "document.scanned",
                          {"document_id": str(uuid.uuid4()), "scan_status": "clean"})  # fmt: skip
    hub_mod.register_filter("document.scanned", lambda a, e: "project_moderator" in a.sources)
    try:
        assert hub.dispatch(scanned) == 0
    finally:
        hub_mod.unregister_filter("document.scanned")
    assert hub.dispatch(scanned) == 1


def test_slow_consumer_is_closed_1013(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    conn = _conn(queue=asyncio.Queue(2))
    event = build_event(conn.user_channel, "session.ended", {"reason": "revoked"})
    assert conn.push(event)
    assert conn.push(event)
    assert not conn.push(event)
    assert conn.close_code == protocol.CLOSE_OVERLOADED
    assert not conn.push(event)
    conn.close(4401)  # повторное закрытие не меняет код
    assert conn.close_code == protocol.CLOSE_OVERLOADED
    items = [conn.queue.get_nowait() for _ in range(conn.queue.qsize())]
    assert items[-1] is None
