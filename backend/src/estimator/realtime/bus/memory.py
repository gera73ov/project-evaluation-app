"""In-memory транспорт шины для тестов (RT-002).

Хранит отправленные события и проверяет каждое полной JSON Schema контракта RT-001
(``$defs.ServerEvent``): событие не по схеме — :class:`EventContractError` прямо в тесте.
``jsonschema`` — dev-зависимость, поэтому модуль не импортируется кодом приложения.
"""

from __future__ import annotations

from typing import Any

from estimator.realtime.bus import Event
from estimator.realtime.bus.contract import EventContractError, check_event, schema


class InMemoryBus:
    def __init__(self, *, validate: bool = True) -> None:
        self.events: list[Event] = []
        self._validate = validate

    async def send(self, event: Event) -> None:
        if self._validate:
            validate_event(event)
        self.events.append(event)

    def on(self, channel: str) -> list[Event]:
        return [e for e in self.events if e["channel"] == channel]

    def names(self) -> list[str]:
        return [e["event"] for e in self.events]


def validate_event(event: Event) -> None:
    """Полная проверка по JSON Schema; иначе :class:`EventContractError` со списком ошибок."""
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    spec = check_event(event)
    doc: dict[str, Any] = schema()
    base = doc.get("$id", "urn:ws")
    registry = Registry().with_resource(
        base, Resource.from_contents(doc, default_specification=DRAFT202012)
    )
    validator = Draft202012Validator(
        {"$ref": f"{base}#/$defs/ServerEvent/oneOf/{spec.index}"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(event), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(
            f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
        )
        raise EventContractError(f"{event['event']}: событие не по схеме RT-001: {details}")
