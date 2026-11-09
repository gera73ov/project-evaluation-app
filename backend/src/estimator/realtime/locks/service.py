"""RT-005 · захваты соединений WebSocket и события ``cell.locked`` / ``cell.unlocked``.

Экземпляр API помнит захваты своих соединений (``Connection.locks``), поэтому событие о снятии
(``released``, ``saved``, ``expired``, ``disconnected``) публикует ровно тот экземпляр, где
открыто соединение-владелец; перехват (``forced``) публикует экземпляр нового владельца.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from estimator.logging import get_logger
from estimator.realtime.bus import build_event, deliver
from estimator.realtime.bus.contract import check_event
from estimator.realtime.locks import Acquired, RedisLocks, iso
from estimator.realtime.locks.iface import LOCK_FIELDS
from estimator.realtime.ws.hub import Connection, Hub

log = get_logger(__name__)

Key = tuple[uuid.UUID, uuid.UUID, str]


async def _publish(project_id: uuid.UUID, event: str, data: dict[str, Any]) -> None:
    message = build_event(f"project:{project_id}", event, data)
    check_event(message)
    await deliver(message)


def _ts(expires_at: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()


class CellLocks:
    def __init__(self, locks: RedisLocks, clock: Callable[[], float] = time.time) -> None:
        self.locks = locks
        self._clock = clock

    async def acquire(self, conn: Connection, key: Key, *, force: bool) -> Acquired:
        project_id, node_id, field = key
        got = await self.locks.acquire(
            project_id, node_id, field, user=conn.user, conn=conn.id, force=force
        )
        conn.locks[key] = _ts(got.expires_at)
        if got.forced_from is not None:
            await _publish(project_id, "cell.unlocked", {
                "node_id": str(node_id), "field": field,
                "user_id": str(got.forced_from.user["id"]), "reason": "forced",
            })  # fmt: skip
        await _publish(project_id, "cell.locked", {
            "node_id": str(node_id), "field": field, "user": conn.user,
            "expires_at": got.expires_at, "forced": got.forced_from is not None,
        })  # fmt: skip
        return got

    async def release(self, conn: Connection, key: Key, reason: str) -> bool:
        """Снять свой захват; событие — только если он ещё был нашим."""
        conn.locks.pop(key, None)
        project_id, node_id, field = key
        if not await self.locks.release(project_id, node_id, field, conn=conn.id):
            return False
        await _publish(project_id, "cell.unlocked", {
            "node_id": str(node_id), "field": field, "user_id": str(conn.user_id), "reason": reason,
        })  # fmt: skip
        return True

    async def release_all(
        self, conn: Connection, reason: str, *, project_id: uuid.UUID | None = None
    ) -> None:
        for key in list(conn.locks):
            if project_id is None or key[0] == project_id:
                try:
                    await self.release(conn, key, reason)
                except Exception:  # Redis недоступен: захват истечёт сам через 30 с
                    log.exception("cell_release_failed")

    async def extend(
        self, conn: Connection, items: Iterable[dict[str, str]]
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """``heartbeat``: продлить перечисленные свои захваты; вернуть продлённые и потерянные."""
        extended: list[dict[str, str]] = []
        lost: list[dict[str, str]] = []
        for item in items:
            node_id, field = uuid.UUID(item["node_id"]), item["field"]
            key = next((k for k in conn.locks if k[1] == node_id and k[2] == field), None)
            expires_at = None
            if key is not None:
                expires_at = await self.locks.extend(
                    key[0], node_id, field, user=conn.user, conn=conn.id
                )
            if expires_at is None:
                if key is not None:
                    conn.locks.pop(key, None)
                lost.append({"node_id": item["node_id"], "field": field})
            else:
                conn.locks[key] = _ts(expires_at)  # type: ignore[index]
                extended.append({"node_id": item["node_id"], "field": field,
                                 "expires_at": expires_at})  # fmt: skip
        return extended, lost

    async def expire(self, conn: Connection) -> None:
        """Захваты, которые не продлили 30 с: снять из учёта и сообщить ``expired``."""
        now = self._clock()
        for key, expires in list(conn.locks.items()):
            if expires > now:
                continue
            holder = await self.locks.holder(*key)
            if holder is not None and holder.conn == conn.id:
                conn.locks[key] = _ts(holder.expires_at)  # продлён с другого экземпляра часов
                continue
            conn.locks.pop(key, None)
            if holder is None:
                project_id, node_id, field = key
                await _publish(project_id, "cell.unlocked", {
                    "node_id": str(node_id), "field": field,
                    "user_id": str(conn.user_id), "reason": "expired",
                })  # fmt: skip

    # --- события из шины (все экземпляры) ---

    async def on_event(self, hub: Hub, event: dict[str, Any]) -> None:
        name = event.get("event")
        if name == "node.updated":
            await self._on_saved(hub, event)
        elif name == "cell.locked":
            self._on_locked(hub, event)

    async def _on_saved(self, hub: Hub, event: dict[str, Any]) -> None:
        """Сохранение поля автором снимает его захват этого поля (``saved``)."""
        data = event.get("data") or {}
        author = str((data.get("author") or {}).get("id", ""))
        node_id = str((data.get("node") or {}).get("id", ""))
        fields = set(data.get("changed_fields") or []) & LOCK_FIELDS
        if not author or not node_id or not fields:
            return
        for conn in hub.connections.values():
            if str(conn.user_id) != author:
                continue
            for key in list(conn.locks):
                if str(key[1]) == node_id and key[2] in fields:
                    await self.release(conn, key, "saved")

    def _on_locked(self, hub: Hub, event: dict[str, Any]) -> None:
        """Ячейку захватил другой (перехват): прежний владелец забывает свой захват."""
        data = event.get("data") or {}
        owner = str((data.get("user") or {}).get("id", ""))
        for conn in hub.connections.values():
            if str(conn.user_id) == owner:
                continue
            for key in list(conn.locks):
                if str(key[1]) == data.get("node_id") and key[2] == data.get("field"):
                    conn.locks.pop(key, None)


__all__ = ["CellLocks", "Key", "iso"]
