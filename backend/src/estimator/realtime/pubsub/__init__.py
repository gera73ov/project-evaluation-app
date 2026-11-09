"""RT-004 · доставка событий между экземплярами API через Redis pub/sub (SPEC 13.3, NFR-REL-05).

* :class:`RedisBus` — транспорт шины RT-002: проверенное событие после ``COMMIT`` публикуется в
  канал Redis ``rt:events``. Его получают все экземпляры API, включая отправителя.
* :class:`Listener` — подписка экземпляра на ``rt:events`` и служебный ``rt:control`` (завершение
  сессий, RT-008). Каждый экземпляр раздаёт событие только своим подписчикам и только по их
  текущим правам (:class:`estimator.realtime.ws.hub.Hub`).

Если связь с Redis оборвалась, события за время обрыва не доходят. Поэтому после
переподключения слушатель вызывает ``on_reconnect``: экземпляр закрывает свои соединения кодом
1012, клиенты подключаются заново с ``since`` и догоняют пропущенное по ``change_log`` (RT-007).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

from estimator.logging import get_logger

log = get_logger(__name__)

EVENTS_CHANNEL = "rt:events"
CONTROL_CHANNEL = "rt:control"
RECONNECT_DELAYS = (0.5, 1.0, 2.0, 5.0)

Message = dict[str, Any]
Handler = Callable[[Message], Awaitable[None] | None]


def encode(message: Message) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()


class RedisBus:
    """Транспорт шины RT-002 на Redis pub/sub."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def send(self, event: Message) -> None:
        await self._redis.publish(EVENTS_CHANNEL, encode(event))


async def publish_control(redis: Redis, message: Message) -> None:
    """Служебное сообщение всем экземплярам (``rt:control``)."""
    await redis.publish(CONTROL_CHANNEL, encode(message))


async def _call(handler: Handler, message: Message) -> None:
    result = handler(message)
    if result is not None:
        await result


class Listener:
    """Фоновая задача: читать ``rt:events`` и ``rt:control``, переподключаться при обрыве."""

    def __init__(
        self,
        redis_url: str,
        *,
        on_event: Handler,
        on_control: Handler,
        on_reconnect: Callable[[], None] | None = None,
        connect_timeout: float = 2.0,
    ) -> None:
        self._url = redis_url
        self._on_event = on_event
        self._on_control = on_control
        self._on_reconnect = on_reconnect
        self._connect_timeout = connect_timeout
        self._task: asyncio.Task[None] | None = None
        self.ready = asyncio.Event()
        #: Имя соединения в ``CLIENT LIST`` Redis (диагностика)
        self.client_name = f"estimator-rt-{uuid.uuid4().hex[:8]}"

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="rt-listener")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self.ready.clear()

    async def _run(self) -> None:
        attempt = 0
        connected_before = False
        while True:
            client = Redis.from_url(
                self._url,
                socket_connect_timeout=self._connect_timeout,
                health_check_interval=30,
                client_name=self.client_name,
            )
            try:
                async with client.pubsub(ignore_subscribe_messages=True) as pubsub:
                    await pubsub.subscribe(EVENTS_CHANNEL, CONTROL_CHANNEL)
                    if connected_before and self._on_reconnect is not None:
                        self._on_reconnect()
                    connected_before = True
                    attempt = 0
                    self.ready.set()
                    async for raw in pubsub.listen():
                        await self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — обрыв Redis: переподключиться
                self.ready.clear()
                log.warning("rt_listener_disconnected", error_type=type(exc).__name__)
            finally:
                await client.aclose()
            await asyncio.sleep(RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)])
            attempt += 1

    async def _handle(self, raw: Message) -> None:
        if raw.get("type") != "message":
            return
        channel = raw["channel"]
        channel = channel.decode() if isinstance(channel, bytes) else str(channel)
        try:
            message = json.loads(raw["data"])
            if not isinstance(message, dict):
                raise ValueError("не объект")
        except ValueError:
            log.warning("rt_message_malformed", channel=channel)
            return
        handler = self._on_event if channel == EVENTS_CHANNEL else self._on_control
        try:
            await _call(handler, message)
        except Exception:  # сбой обработки одного события не останавливает слушателя
            log.exception("rt_message_failed", channel=channel)
