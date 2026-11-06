"""RT-002: шина проверяет событие по контракту RT-001 до отправки (ARCH-01, SEC-AUTHZ-04)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from estimator.realtime import bus
from estimator.realtime.bus import contract
from estimator.realtime.bus.contract import EventContractError, check_event
from estimator.realtime.bus.memory import InMemoryBus, validate_event
from estimator.realtime.locks import iface as locks

pytestmark = [pytest.mark.spec("ARCH-01"), pytest.mark.spec("13.3")]

PROJECT = str(uuid.uuid4())
USER = str(uuid.uuid4())
NODE = str(uuid.uuid4())


def _event(name: str, channel: str, data: dict[str, Any], version: int | None = None):
    return bus.build_event(channel, name, data, project_version=version)


def _unlocked(**over: Any) -> dict[str, Any]:
    data = {"node_id": NODE, "field": "r", "user_id": USER, "reason": "saved"}
    return _event("cell.unlocked", f"project:{PROJECT}", {**data, **over})


def test_all_contract_events_are_known() -> None:
    specs = contract.events()
    assert len(specs) == 25
    assert specs["money.updated"].channel == "money"
    assert specs["note.created"].channel == "notes"
    assert specs["session.ended"].channel == "user"
    assert specs["node.updated"].versioned
    assert not specs["cell.locked"].versioned


def test_money_keys_cover_contract_money_event_only() -> None:
    """Набор денежных ключей не задевает ни одно событие вне :money (иначе ложные отказы)."""
    for spec in contract.events().values():
        if spec.channel != "money":
            assert not spec.data_keys & contract.MONEY_KEYS, spec.name
    assert contract.events()["money.updated"].data_keys & contract.MONEY_KEYS


def test_valid_events_pass_full_schema() -> None:
    validate_event(_unlocked())
    validate_event(_event("session.ended", f"user:{USER}", {"reason": "revoked"}))
    validate_event(
        _event("member.updated", f"project:{PROJECT}", {"user_ids": [USER], "change": "added"}, 3)
    )
    money = {"totals": {"cost_rub": "12500000", "quote_rub": None, "quote_cur": None}}
    validate_event(_event("money.updated", f"project:{PROJECT}:money", money, 4))


@pytest.mark.parametrize(
    ("message", "fragment"),
    [
        (_event("node.teleported", f"project:{PROJECT}", {}), "отсутствует в контракте"),
        (_event("session.ended", f"project:{PROJECT}", {"reason": "revoked"}), "канал вида"),
        (_event("session.ended", "lobby", {"reason": "revoked"}), "неизвестный канал"),
        (
            _event("member.updated", f"project:{PROJECT}", {"user_ids": [USER], "change": "added"}),
            "нужен project_version",
        ),
        (
            _event("session.ended", f"user:{USER}", {"reason": "revoked"}, 7),
            "не несёт project_version",
        ),
        (_unlocked(extra=1), "ключи data не из контракта"),
        (_event("session.ended", f"user:{USER}", {}), "нет обязательных ключей"),
    ],
)
def test_check_event_rejects(message: dict[str, Any], fragment: str) -> None:
    with pytest.raises(EventContractError, match=fragment):
        check_event(message)


@pytest.mark.spec("SEC-AUTHZ-04")
@pytest.mark.spec("TC-SEC-03")
def test_money_never_leaks_outside_money_channel() -> None:
    """Деньги во вложенных данных события канала проекта — отказ ещё до отправки."""
    assert contract.money_keys_in({"a": [{"b": {"cost_rub": "1"}}]}) == ["data.a[0].b.cost_rub"]
    leaking = _event(
        "project.updated",
        f"project:{PROJECT}",
        {"author": {"id": USER, "full_name": "А"}, "changes": {"currency": "USD"}},
        5,
    )
    with pytest.raises(EventContractError, match="денежные ключи"):
        check_event(leaking)


def test_full_schema_catches_what_quick_check_misses() -> None:
    bad = _unlocked(field="budget", reason="whatever")
    check_event(bad)  # ключи верные — быстрая проверка пропускает
    with pytest.raises(EventContractError, match="не по схеме RT-001"):
        validate_event(bad)


def test_build_event_shape() -> None:
    moment = datetime(2026, 11, 6, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    message = bus.build_event(f"user:{USER}", "session.ended", {"reason": "revoked"}, ts=moment)
    assert message == {
        "type": "event",
        "event": "session.ended",
        "channel": f"user:{USER}",
        "ts": "2026-11-06T12:00:00.000Z",
        "data": {"reason": "revoked"},
    }
    assert "project_version" not in message
    assert bus.build_event(f"user:{USER}", "x", {})["ts"].endswith("Z")
    assert datetime.fromisoformat(message["ts"]).tzinfo == UTC


async def test_in_memory_bus_records_and_validates() -> None:
    memory = InMemoryBus()
    await memory.send(_unlocked())
    assert memory.names() == ["cell.unlocked"]
    assert memory.on(f"project:{PROJECT}") == memory.events
    with pytest.raises(EventContractError):
        await memory.send(_unlocked(field="budget"))
    lax = InMemoryBus(validate=False)
    await lax.send({"event": "anything", "channel": "x"})
    assert lax.names() == ["anything"]


async def test_deliver_swallows_transport_errors() -> None:
    class Broken:
        async def send(self, event: bus.Event) -> None:
            raise ConnectionError("redis down")

    previous = bus.set_bus(Broken())
    try:
        await bus.deliver(_unlocked())  # не бросает: данные уже зафиксированы
    finally:
        bus.set_bus(previous)
    assert bus.get_bus() is previous


async def test_null_bus_drops() -> None:
    await bus.NullBus().send(_unlocked())


async def test_lock_interface_stub_and_replacement() -> None:
    ids = (uuid.uuid4(), uuid.uuid4())
    await locks.assert_not_locked(*ids, "r", user_id=uuid.uuid4())
    with pytest.raises(ValueError, match="не захватывается"):
        await locks.assert_not_locked(*ids, "e", user_id=uuid.uuid4())

    calls: list[str] = []

    class Recorder:
        async def assert_not_locked(self, project_id, node_id, field, *, user_id) -> None:
            calls.append(field)

    previous = locks.set_lock_checker(Recorder())
    try:
        await locks.assert_not_locked(*ids, "o", user_id=uuid.uuid4())
    finally:
        locks.set_lock_checker(previous)
    assert calls == ["o"]
    assert isinstance(previous, locks.NoLocks)


@pytest.mark.spec("BR-MONEY-04")
def test_money_amounts_are_not_capped() -> None:
    """CR-002: суммы в рублях — целые без ограничения разрядности, как MoneyString в OpenAPI."""
    channel = f"project:{PROJECT}:money"
    big = {
        "totals": {"cost_rub": "1250000000", "quote_rub": "987654321", "quote_cur": "12397"},
        "contract_amount": "1500000000",
        "rates": [{"discipline_id": None, "rate_rub": "250000"}],
        "vat_percent": "20",
    }
    validate_event(_event("money.updated", channel, big, 9))
    fraction = {"totals": {"cost_rub": "100.5", "quote_rub": None, "quote_cur": None}}
    with pytest.raises(EventContractError, match="не по схеме"):
        validate_event(_event("money.updated", channel, fraction, 9))
