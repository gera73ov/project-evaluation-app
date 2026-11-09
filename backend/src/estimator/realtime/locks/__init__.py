"""RT-005 · захват ячеек «узел + поле» на Redis (FR-TREE-31, 15.4, 15.3 ``CELL_LOCKED``).

Ключ ``lock:{project_id}:{node_id}:{field}`` со сроком 30 с, значение —
``{"user": UserRef, "conn": соединение, "expires_at": ISO}``. Захват держит соединение
WebSocket: продлевает ``heartbeat`` каждые 10 с, снимают ``unlock``, сохранение поля автором,
закрытие соединения, истечение срока и перехват модератором (``force``). Все проверки владельца
атомарны (скрипты Lua), поэтому из нескольких экземпляров API событие о снятии публикует один.

:class:`RedisLockChecker` — реальная проверка ``assert_not_locked`` для ядра (RT-002 iface):
PATCH поля, захваченного другим пользователем, получает 423 ``CELL_LOCKED`` с ``locked_by``,
``field`` и ``node_id`` (contracts/errors.yaml). Захват своим же пользователем (другая вкладка)
правку не блокирует.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from estimator.api.common.errors import ApiError

KEY_PREFIX = "lock:"
TTL_SECONDS = 30
#: Сколько захватов одновременно держит одно соединение (``heartbeat`` продлевает до 20)
MAX_PER_CONNECTION = 20

_ACQUIRE = """
local cur = redis.call('GET', KEYS[1])
if cur then
  local owner = cjson.decode(cur)['user']['id']
  if owner ~= ARGV[1] and ARGV[4] ~= '1' then return {0, cur} end
  redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3])
  if owner ~= ARGV[1] then return {2, cur} end
  return {1, cur}
end
redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3])
return {1}
"""
_RELEASE = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
if cjson.decode(cur)['conn'] ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""
_EXTEND = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
if cjson.decode(cur)['conn'] ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3])
return 1
"""


def lock_key(project_id: uuid.UUID, node_id: uuid.UUID, field: str) -> str:
    return f"{KEY_PREFIX}{project_id}:{node_id}:{field}"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Holder:
    """Текущий владелец захвата."""

    user: dict[str, Any]
    conn: str
    expires_at: str

    @classmethod
    def parse(cls, raw: bytes | str) -> Holder:
        value = json.loads(raw)
        return cls(user=value["user"], conn=str(value["conn"]), expires_at=str(value["expires_at"]))


@dataclass(frozen=True)
class Acquired:
    expires_at: str
    #: Прежний владелец, если захват перехвачен (``force``)
    forced_from: Holder | None = None


class CellLocked(Exception):
    """Поле захвачено другим пользователем."""

    def __init__(self, holder: Holder) -> None:
        super().__init__("CELL_LOCKED")
        self.holder = holder


class RedisLocks:
    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    def _value(self, user: dict[str, Any], conn: str) -> tuple[str, str]:
        expires_at = iso(self._clock() + TTL_SECONDS)
        payload = json.dumps({"user": user, "conn": conn, "expires_at": expires_at})
        return payload, expires_at

    async def acquire(
        self,
        project_id: uuid.UUID,
        node_id: uuid.UUID,
        field: str,
        *,
        user: dict[str, Any],
        conn: str,
        force: bool = False,
    ) -> Acquired:
        payload, expires_at = self._value(user, conn)
        result = await self._redis.eval(  # type: ignore[misc]
            _ACQUIRE, 1, lock_key(project_id, node_id, field),
            str(user["id"]), payload, str(TTL_SECONDS * 1000), "1" if force else "0",
        )  # fmt: skip
        status = int(result[0])
        if status == 0:
            raise CellLocked(Holder.parse(result[1]))
        previous = Holder.parse(result[1]) if status == 2 else None
        return Acquired(expires_at, previous)

    async def release(
        self, project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, conn: str
    ) -> bool:
        key = lock_key(project_id, node_id, field)
        return bool(await self._redis.eval(_RELEASE, 1, key, conn))  # type: ignore[misc]

    async def extend(
        self,
        project_id: uuid.UUID,
        node_id: uuid.UUID,
        field: str,
        *,
        user: dict[str, Any],
        conn: str,
    ) -> str | None:
        """Продлить свой захват; ``None`` — захвата больше нет (истёк или перехвачен)."""
        payload, expires_at = self._value(user, conn)
        key = lock_key(project_id, node_id, field)
        ok = await self._redis.eval(  # type: ignore[misc]
            _EXTEND, 1, key, conn, payload, str(TTL_SECONDS * 1000)
        )
        return expires_at if ok else None

    async def holder(self, project_id: uuid.UUID, node_id: uuid.UUID, field: str) -> Holder | None:
        raw = await self._redis.get(lock_key(project_id, node_id, field))
        return Holder.parse(raw) if raw else None


class RedisLockChecker:
    """Реализация ``locks.iface.LockChecker`` для ядра (PATCH узла)."""

    def __init__(self, locks: RedisLocks) -> None:
        self._locks = locks

    async def assert_not_locked(
        self, project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, user_id: uuid.UUID
    ) -> None:
        holder = await self._locks.holder(project_id, node_id, field)
        if holder is not None and holder.user.get("id") != str(user_id):
            raise ApiError("CELL_LOCKED", locked_by=holder.user, field=field, node_id=str(node_id))
