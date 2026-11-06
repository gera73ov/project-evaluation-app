"""Контракт WebSocket-событий RT-001 для шины RT-002 (``contracts/ws-events.schema.json``).

Из схемы берётся то, что шина проверяет при каждой публикации, без зависимостей сверх стека:
известное имя события, вид канала (``x-channel``), обязательность ``project_version`` и
допустимые ключи ``data``. Полная проверка по JSON Schema — в :class:`InMemoryBus` для тестов
(``jsonschema`` есть только в dev-зависимостях): событие не по схеме роняет тест трека, который
его публикует.

Файл схемы ищется так же, как каталог прав (SEC-005): переменная ``ESTIMATOR_WS_SCHEMA_FILE``,
копия рядом с модулем (кладётся при сборке образа) или ``contracts/`` репозитория.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

FILE_NAME = "ws-events.schema.json"
ENV_PATH = "ESTIMATOR_WS_SCHEMA_FILE"

#: Денежные ключи (contracts/ws-events.md, SEC-AUTHZ-04, TC-SEC-03): вне канала ``:money`` их нет
#: ни на каком уровне вложенности. Список шире перечня ws-events.md: в него входят и ключи
#: ``MoneyTotals`` (тот же набор проверяет tests/unit/rt/test_ws_events_contract.py)
MONEY_KEYS = frozenset(
    {
        "rate",
        "rates",
        "rate_rub",
        "cost",
        "cost_rub",
        "currency",
        "exchange_rate",
        "money",
        "vat",
        "vat_percent",
        "vat_rub",
        "total_with_vat_rub",
        "contract_amount",
        "quote_rub",
        "quote_cur",
        "totals",
    }
)

_CHANNELS = {
    "project": re.compile(r"^project:[0-9a-f-]{36}$"),
    "money": re.compile(r"^project:[0-9a-f-]{36}:money$"),
    "notes": re.compile(r"^project:[0-9a-f-]{36}:notes$"),
    "user": re.compile(r"^user:[0-9a-f-]{36}$"),
}


class EventContractError(ValueError):
    """Событие не соответствует контракту RT-001; публикация отклоняется."""


@dataclass(frozen=True)
class EventSpec:
    name: str
    channel: str  # project | money | notes | user
    versioned: bool
    data_keys: frozenset[str]
    data_required: frozenset[str]
    index: int  # номер варианта в $defs.ServerEvent.oneOf


def schema_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    packaged = Path(__file__).with_name(FILE_NAME)
    if packaged.is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / FILE_NAME
        if candidate.is_file():
            return candidate
    raise EventContractError(f"не найден {FILE_NAME}: ни рядом с модулем, ни в contracts/")


@cache
def schema() -> dict[str, Any]:
    return json.loads(schema_path().read_text(encoding="utf-8"))


@cache
def events() -> dict[str, EventSpec]:
    """``{имя события: описание}`` из ``$defs.ServerEvent``."""
    specs: dict[str, EventSpec] = {}
    for index, variant in enumerate(schema()["$defs"]["ServerEvent"]["oneOf"]):
        name = variant["properties"]["event"]["const"]
        data = variant["properties"]["data"]
        specs[name] = EventSpec(
            name=name,
            channel=variant["x-channel"],
            versioned="project_version" in variant.get("required", []),
            data_keys=frozenset(data.get("properties", {})),
            data_required=frozenset(data.get("required", [])),
            index=index,
        )
    return specs


def channel_kind(channel: str) -> str:
    for kind, pattern in _CHANNELS.items():
        if pattern.fullmatch(channel):
            return kind
    raise EventContractError(f"неизвестный канал {channel!r}")


def money_keys_in(value: Any, path: str = "data") -> list[str]:
    """Пути денежных ключей во вложенной структуре."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if key in MONEY_KEYS:
                found.append(here)
            found.extend(money_keys_in(item, here))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(money_keys_in(item, f"{path}[{i}]"))
    return found


def check_event(message: dict[str, Any]) -> EventSpec:
    """Быстрая проверка события перед публикацией; иначе :class:`EventContractError`."""
    name = message.get("event")
    spec = events().get(str(name))
    if spec is None:
        raise EventContractError(f"событие {name!r} отсутствует в контракте RT-001")
    kind = channel_kind(str(message.get("channel", "")))
    if kind != spec.channel:
        raise EventContractError(f"{name}: канал вида {kind!r}, по контракту {spec.channel!r}")
    has_version = message.get("project_version") is not None
    if spec.versioned and not has_version:
        raise EventContractError(f"{name}: нужен project_version (ARCH-02)")
    if not spec.versioned and has_version:
        raise EventContractError(f"{name}: событие не несёт project_version")
    data = message.get("data")
    if not isinstance(data, dict):
        raise EventContractError(f"{name}: data должен быть объектом")
    if extra := sorted(set(data) - spec.data_keys):
        raise EventContractError(f"{name}: ключи data не из контракта: {extra}")
    if missing := sorted(spec.data_required - set(data)):
        raise EventContractError(f"{name}: нет обязательных ключей data: {missing}")
    if kind != "money" and (leaks := money_keys_in(data)):
        raise EventContractError(f"{name}: денежные ключи вне канала :money: {leaks}")
    return spec
