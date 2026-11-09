"""Соединения WebSocket экземпляра API и раздача событий подписчикам (RT-003, RT-004; SPEC 13.3).

:class:`Hub` знает, какие соединения этого процесса подписаны на какие каналы. Событие из шины
(через Redis — от любого экземпляра) уходит только в соединения, подписанные на его канал, и
только если подписчик проходит фильтр по правам (:func:`visible`). Права подписчика
(:class:`ProjectAccess`) пересчитываются по актуальным данным БД при подписке и периодически
(RT-008), поэтому индекс каналов всегда отражает текущие права, а не права на момент подписки.

Отправка неблокирующая: у каждого соединения своя очередь; клиент, который не успевает
принимать события, отключается кодом 1013 и догоняет изменения по ``subscribe {since}``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from estimator.logging import get_logger
from estimator.realtime.bus.contract import channel_kind, money_keys_in
from estimator.realtime.ws.protocol import CLOSE_OVERLOADED

log = get_logger(__name__)

QUEUE_SIZE = 1000
Message = dict[str, Any]


@dataclass(frozen=True)
class ProjectAccess:
    """Права подписчика в проекте: какие каналы ему положены сейчас."""

    project_id: uuid.UUID
    money: bool = False
    notes: bool = False
    #: Роли, через которые получен доступ (``project_moderator``, ``expert``, ``admin`` …)
    sources: frozenset[str] = frozenset()

    @property
    def channels(self) -> frozenset[str]:
        base = f"project:{self.project_id}"
        out = {base}
        if self.money:
            out.add(f"{base}:money")
        if self.notes:
            out.add(f"{base}:notes")
        return frozenset(out)


@dataclass(eq=False)
class Connection:
    """Одно соединение WebSocket: пользователь, сессия, подписки и очередь отправки."""

    user_id: uuid.UUID
    session_id: str = field(repr=False)
    session_hash: bytes = field(repr=False)
    user: dict[str, Any] = field(default_factory=dict)
    roles: frozenset[str] = frozenset()
    support_projects: frozenset[uuid.UUID] = frozenset()
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    projects: dict[uuid.UUID, ProjectAccess] = field(default_factory=dict)
    queue: asyncio.Queue[Message | None] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    close_code: int | None = None
    close_reason: str = ""
    #: Перепроверить права немедленно (``member.updated`` о пользователе, RT-008)
    recheck: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def user_channel(self) -> str:
        return f"user:{self.user_id}"

    @property
    def channels(self) -> frozenset[str]:
        out = {self.user_channel}
        for access in self.projects.values():
            out |= access.channels
        return frozenset(out)

    @property
    def closing(self) -> bool:
        return self.close_code is not None

    def push(self, message: Message) -> bool:
        """Поставить сообщение в очередь; переполнение — отключение кодом 1013."""
        if self.closing:
            return False
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("ws_queue_overflow", user_id=str(self.user_id))
            self.close(CLOSE_OVERLOADED, "slow consumer")
            return False
        return True

    def close(self, code: int, reason: str = "") -> None:
        """Попросить писателя закрыть соединение после уже поставленных сообщений."""
        if self.closing:
            return
        self.close_code, self.close_reason = code, reason
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            # Очередь полна: освободить место под сигнал закрытия, события клиенту уже не нужны
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)


#: Дополнительный фильтр события по правам подписчика: ``(доступ, событие) → отдавать ли``.
#: Регистрируют домены, у которых правило тоньше канала (например, ``document.scanned`` о
#: документе в корзине — только модератору и пресейлу, GAP-06).
EventFilter = Callable[[ProjectAccess, Message], bool]
_FILTERS: dict[str, EventFilter] = {}


def register_filter(event: str, check: EventFilter) -> None:
    _FILTERS[event] = check


def unregister_filter(event: str) -> None:
    _FILTERS.pop(event, None)


def _project_of(channel: str) -> uuid.UUID | None:
    if not channel.startswith("project:"):
        return None
    return uuid.UUID(channel.split(":")[1])


def visible(conn: Connection, event: Message, *, strict: bool = False) -> bool:
    """Положено ли событие подписчику по его текущим правам."""
    channel = event["channel"]
    if channel == conn.user_channel:
        return True
    project_id = _project_of(channel)
    access = conn.projects.get(project_id) if project_id else None
    if access is None or channel not in access.channels:
        return False
    if strict and channel_kind(channel) != "money" and money_keys_in(event.get("data")):
        # Шина уже не пропускает такие события (RT-002); вторая проверка — на стендах dev/test
        log.error("ws_money_leak_blocked", ws_event=event.get("event"), channel=channel)
        return False
    check = _FILTERS.get(str(event.get("event")))
    return check is None or check(access, event)


class Hub:
    """Соединения процесса и индекс «канал → соединения»."""

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict
        self.connections: dict[str, Connection] = {}
        self._by_channel: dict[str, set[Connection]] = {}

    # --- соединения и подписки ---

    def add(self, conn: Connection) -> None:
        self.connections[conn.id] = conn
        self._index(conn, frozenset(), conn.channels)

    def remove(self, conn: Connection) -> None:
        self.connections.pop(conn.id, None)
        self._index(conn, conn.channels, frozenset())

    def set_access(self, conn: Connection, access: ProjectAccess) -> None:
        """Подписать (или переподписать с новыми правами) соединение на проект."""
        before = conn.channels
        conn.projects[access.project_id] = access
        self._index(conn, before, conn.channels)

    def drop_project(self, conn: Connection, project_id: uuid.UUID) -> bool:
        before = conn.channels
        if conn.projects.pop(project_id, None) is None:
            return False
        self._index(conn, before, conn.channels)
        return True

    def _index(self, conn: Connection, before: frozenset[str], after: frozenset[str]) -> None:
        if conn.id not in self.connections:
            after = frozenset()
        for channel in before - after:
            subscribers = self._by_channel.get(channel)
            if subscribers is not None:
                subscribers.discard(conn)
                if not subscribers:
                    del self._by_channel[channel]
        for channel in after - before:
            self._by_channel.setdefault(channel, set()).add(conn)

    # --- выборки ---

    def subscribers(self, channel: str) -> frozenset[Connection]:
        return frozenset(self._by_channel.get(channel, ()))

    def by_session(self, session_hash: bytes) -> list[Connection]:
        return [c for c in self.connections.values() if c.session_hash == session_hash]

    def by_user(self, user_id: uuid.UUID) -> list[Connection]:
        return [c for c in self.connections.values() if c.user_id == user_id]

    def projects(self) -> set[uuid.UUID]:
        return {pid for c in self.connections.values() for pid in c.projects}

    def in_project(self, project_id: uuid.UUID) -> list[Connection]:
        return [c for c in self.connections.values() if project_id in c.projects]

    # --- раздача ---

    def dispatch(self, event: Message) -> int:
        """Раздать событие подписчикам канала, прошедшим фильтр; вернуть число получателей."""
        delivered = 0
        for conn in self.subscribers(str(event.get("channel", ""))):
            if visible(conn, event, strict=self.strict) and conn.push(event):
                delivered += 1
        return delivered

    def close_all(
        self, code: int, reason: str = "", conns: Iterable[Connection] | None = None
    ) -> None:
        for conn in list(conns if conns is not None else self.connections.values()):
            conn.close(code, reason)
