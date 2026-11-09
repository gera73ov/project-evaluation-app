"""RT-006 · «Кто сейчас в проекте» (SPEC 15.4 ``presence``, 11.4 №4).

Список хранится в Redis, общий для всех экземпляров API: хэш ``presence:{project_id}``, поле —
соединение WebSocket, значение — ``{"user": UserRef, "ts": время отметки}``. Подписка добавляет
поле, отписка и закрытие соединения удаляют его; после каждого изменения событие ``presence``
с полным списком уходит в ``project:{id}`` через шину.

Если экземпляр API упал, его поля не удалятся сами: каждый экземпляр раз в
:data:`SWEEP_SECONDS` обновляет отметки своих соединений, а записи старше :data:`TTL_SECONDS`
выбрасываются при чтении — пользователь исчезает из списка не позже чем через 30 с.
Один человек с двумя вкладками показывается один раз; цвет — как у рамки захвата (DESIGN 2.6).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from redis.asyncio import Redis

from estimator.realtime.bus import build_event, deliver
from estimator.realtime.bus.contract import check_event

KEY_PREFIX = "presence:"
TTL_SECONDS = 30
SWEEP_SECONDS = 10
KEY_TTL_SECONDS = 120  # весь хэш исчезает, если ни один экземпляр его не обновляет


def _key(project_id: uuid.UUID) -> str:
    return f"{KEY_PREFIX}{project_id}"


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class Presence:
    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    async def join(self, project_id: uuid.UUID, conn_id: str, user: dict[str, Any]) -> None:
        await self._write(project_id, {conn_id: user})
        await self.broadcast(project_id)

    async def leave(self, project_id: uuid.UUID, conn_id: str) -> None:
        removed = await self._redis.hdel(_key(project_id), conn_id)
        if removed:
            await self.broadcast(project_id)

    async def refresh(self, project_id: uuid.UUID, entries: dict[str, dict[str, Any]]) -> None:
        """Обновить отметки соединений этого экземпляра."""
        if entries:
            await self._write(project_id, entries)

    async def _write(self, project_id: uuid.UUID, entries: dict[str, dict[str, Any]]) -> None:
        now = self._clock()
        mapping = {cid: json.dumps({"user": user, "ts": now}) for cid, user in entries.items()}
        key = _key(project_id)
        await self._redis.hset(key, mapping=mapping)  # type: ignore[arg-type]
        await self._redis.expire(key, KEY_TTL_SECONDS)

    async def users(self, project_id: uuid.UUID) -> tuple[list[dict[str, Any]], bool]:
        """Список ``UserRef`` без повторов и признак «выброшены устаревшие записи»."""
        key = _key(project_id)
        raw = await self._redis.hgetall(key)
        deadline = self._clock() - TTL_SECONDS
        stale: list[str] = []
        users: dict[str, dict[str, Any]] = {}
        for conn_id, value in raw.items():
            try:
                entry = json.loads(value)
                user, ts = entry["user"], float(entry["ts"])
            except (ValueError, KeyError, TypeError):
                stale.append(_text(conn_id))
                continue
            if ts < deadline:
                stale.append(_text(conn_id))
                continue
            users.setdefault(str(user["id"]), user)
        if stale:
            await self._redis.hdel(key, *stale)
        ordered = sorted(users.values(), key=lambda u: (u.get("full_name", ""), u["id"]))
        return ordered, bool(stale)

    async def broadcast(self, project_id: uuid.UUID) -> None:
        users, _ = await self.users(project_id)
        event = build_event(f"project:{project_id}", "presence", {"users": users})
        check_event(event)
        await deliver(event)

    async def sweep(self, local: Iterable[tuple[uuid.UUID, dict[str, dict[str, Any]]]]) -> None:
        """Обновить свои отметки и разослать список там, где выброшены чужие устаревшие."""
        for project_id, entries in local:
            await self.refresh(project_id, entries)
            _, pruned = await self.users(project_id)
            if pruned:
                await self.broadcast(project_id)
