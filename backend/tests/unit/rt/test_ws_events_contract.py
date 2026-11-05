"""RT-001: contracts/ws-events.schema.json описывает все события и команды 15.4."""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.unit._contracts import load_json, spec_table

pytestmark = [pytest.mark.spec("15.4"), pytest.mark.spec("SEC-AUTHZ-04")]

W = load_json("ws-events.schema.json")
EVENTS = {e["properties"]["event"]["const"]: e for e in W["$defs"]["ServerEvent"]["oneOf"]}
COMMANDS = {c["properties"]["op"]["const"] for c in W["$defs"]["ClientCommand"]["oneOf"]}
MONEY_KEYS = {
    "rate", "rates", "rate_rub", "cost", "cost_rub", "currency", "exchange_rate", "money",
    "vat", "vat_percent", "vat_rub", "contract_amount", "quote_rub", "quote_cur", "totals",
}  # fmt: skip


def _names(cells: list[str]) -> set[str]:
    return set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)?)`", " ".join(cells)))


def _keys(schema: Any, defs: dict) -> set[str]:
    """Все имена свойств, достижимые из схемы (с раскрытием $ref)."""
    out: set[str] = set()
    if isinstance(schema, dict):
        if "$ref" in schema:
            return _keys(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
        out |= set(schema.get("properties", {}))
        for v in schema.values():
            out |= _keys(v, defs)
    elif isinstance(schema, list):
        for v in schema:
            out |= _keys(v, defs)
    return out


def test_all_events_and_commands_of_15_4():
    rows = spec_table("### 15.4. События WebSocket")
    assert _names([r[0] for r in rows]) == set(EVENTS)
    cmd_rows = spec_table("| Команда (клиент → сервер) | Назначение |", skip_header=False)
    assert _names([r[0] for r in cmd_rows]) == COMMANDS


def test_money_and_notes_only_in_own_channels():
    defs = W["$defs"]
    for name, ev in EVENTS.items():
        channel = ev["x-channel"]
        keys = _keys(ev["properties"]["data"], defs)
        if channel != "money":
            assert keys & MONEY_KEYS == set(), name
        if name.startswith("note."):
            assert channel == "notes"
        if name == "money.updated":
            assert channel == "money"
    assert W["x-channels"]["money"]["requires"] == "money.read"
    assert W["x-channels"]["notes"]["requires"] == "notes.read"


def test_project_updated_forbids_money_keys():
    data = EVENTS["project.updated"]["properties"]["data"]
    banned = set(data["properties"]["changes"]["propertyNames"]["not"]["enum"])
    assert {"currency", "exchange_rate", "contract_amount", "rates"} <= banned


def test_limits_match_spec():
    lim = W["x-limits"]
    assert lim["max_message_bytes"] == 64 * 1024  # SEC-WEB-08
    assert (lim["lock_ttl_seconds"], lim["lock_renew_seconds"]) == (30, 10)  # FR-TREE-31
    assert lim["close_after_session_end_seconds"] == 5  # FR-SESS-02


def test_lock_requires_known_field_and_force_flag():
    lock = next(c for c in W["$defs"]["ClientCommand"]["oneOf"] if c["title"] == "lock")
    assert set(lock["required"]) == {"op", "project_id", "node_id", "field"}
    assert "force" in lock["properties"]
