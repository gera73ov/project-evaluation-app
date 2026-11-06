"""RT-002 · шина доменных событий (SPEC ARCH-01, ARCH-02, 13.3, NFR-REL-04).

Код ядра, обсуждений и уведомлений публикует событие в той же транзакции, где меняет данные::

    from estimator.realtime.bus import publish

    publish(db, f"project:{project.id}", "node.updated",
            {"node": node_dto, "author": author_ref, "changed_fields": ["r"]},
            project_version=project.version)

Событие сразу проверяется по контракту RT-001 (:func:`check_event`): ошибка — исключение в коде,
который публикует, и откат его транзакции. Отправка — только после ``COMMIT`` (хук DB-011
:func:`estimator.db.session.after_commit`): при откате событие не уходит никому (ARCH-01).

Транспорт — реализация :class:`EventBus`, заданная :func:`set_bus`. RT-004 подключит Redis
pub/sub с фильтрацией по правам подписчиков; до этого по умолчанию стоит :class:`NullBus`
(событие пишется в лог и отбрасывается). Тесты ставят :class:`InMemoryBus`, который ещё и
проверяет событие полной JSON Schema. Сбой отправки не ломает запрос: данные уже
зафиксированы, а клиенты догонят изменения по ``change_log`` (``subscribe`` с ``since``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from estimator.db.session import after_commit
from estimator.logging import get_logger
from estimator.realtime.bus.contract import EventContractError, check_event

log = get_logger(__name__)

Event = dict[str, Any]


class EventBus(Protocol):
    """Транспорт событий: получает уже проверенное событие после commit."""

    async def send(self, event: Event) -> None: ...


class NullBus:
    """Транспорт по умолчанию до RT-004: событие только в лог (без данных)."""

    async def send(self, event: Event) -> None:
        log.debug("realtime_event_dropped", ws_event=event["event"], channel=event["channel"])


_bus: EventBus = NullBus()


def set_bus(bus: EventBus) -> EventBus:
    """Подключить транспорт; возвращает прежний (чтобы тест мог вернуть его на место)."""
    global _bus
    previous, _bus = _bus, bus
    return previous


def get_bus() -> EventBus:
    return _bus


def build_event(
    channel: str,
    event: str,
    data: Mapping[str, Any],
    *,
    project_version: int | None = None,
    ts: datetime | None = None,
) -> Event:
    """Сообщение ``ServerEvent`` контракта RT-001 (``ts`` — UTC, ISO 8601 с ``Z``)."""
    moment = (ts or datetime.now(UTC)).astimezone(UTC)
    message: Event = {
        "type": "event",
        "event": event,
        "channel": channel,
        "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "data": dict(data),
    }
    if project_version is not None:
        message["project_version"] = project_version
    return message


async def deliver(event: Event) -> None:
    """Отправить событие текущим транспортом; сбой — в лог, не исключением."""
    try:
        await _bus.send(event)
    except Exception as exc:  # noqa: BLE001 — данные уже зафиксированы, клиенты догонят по change_log
        log.warning(
            "realtime_publish_failed",
            ws_event=event["event"],
            channel=event["channel"],
            error_type=type(exc).__name__,
        )


def publish(
    session: AsyncSession | Session,
    channel: str,
    event: str,
    data: Mapping[str, Any],
    *,
    project_version: int | None = None,
) -> Event:
    """Проверить событие сейчас и отправить его после commit транзакции ``session``."""
    message = build_event(channel, event, data, project_version=project_version)
    check_event(message)

    async def send_after_commit() -> None:
        await deliver(message)

    after_commit(session, send_after_commit)
    return message


__all__ = [
    "Event",
    "EventBus",
    "EventContractError",
    "NullBus",
    "build_event",
    "deliver",
    "get_bus",
    "publish",
    "set_bus",
]
