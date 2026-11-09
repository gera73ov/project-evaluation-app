"""Совместная работа в процессе API: хаб соединений, Redis pub/sub, присутствие, отзыв сессий.

:class:`Realtime` создаётся в :func:`estimator.main.create_app` (``app.state.realtime``), фоновые
задачи запускает lifespan приложения:

* шина RT-002 переключается на :class:`~estimator.realtime.pubsub.RedisBus` (RT-004);
* :class:`~estimator.realtime.pubsub.Listener` раздаёт события из Redis своим подписчикам и
  выполняет служебные сообщения (``session_ended``, RT-008);
* слушатель сервиса сессий AUTH-002 рассылает завершение сессии всем экземплярам;
* раз в 10 с обновляются отметки присутствия своих соединений (RT-006).

Остановка процесса (поочерёдный перезапуск, 18.3) закрывает соединения кодом 1012: клиенты
переподключаются к другой реплике с ``since``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.sessions import (
    SessionEnded,
    SessionService,
    add_session_ended_listener,
    remove_session_ended_listener,
)
from estimator.config import AppEnv, Settings
from estimator.db.session import transaction
from estimator.logging import get_logger
from estimator.realtime.bus import EventBus, set_bus
from estimator.realtime.locks import RedisLockChecker, RedisLocks
from estimator.realtime.locks.iface import LockChecker, set_lock_checker
from estimator.realtime.locks.service import CellLocks
from estimator.realtime.presence import SWEEP_SECONDS, Presence
from estimator.realtime.pubsub import Listener, RedisBus, publish_control
from estimator.realtime.revoke import CONTROL_SESSION_ENDED, session_ended_message
from estimator.realtime.ws import end_connection
from estimator.realtime.ws.hub import Hub
from estimator.realtime.ws.protocol import CLOSE_RESTART

log = get_logger(__name__)

#: Перепроверка сессии и прав каждого соединения (FR-SESS-05: ≤ 5 с)
REVALIDATE_SECONDS = 2.0

DbFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def allowed_origin_hosts(settings: Settings) -> frozenset[str]:
    """Хосты для ``Origin`` (SEC-WEB-04): адрес приложения и имена из ``TRUSTED_HOSTS``."""
    hosts = {settings.app_base_url.split("://", 1)[1].split("/", 1)[0]}
    hosts |= {h for h in settings.trusted_hosts if h and "*" not in h}
    return frozenset(hosts)


class Realtime:
    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        *,
        db: DbFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.db: DbFactory = db or transaction
        self.clock = clock
        self.hub = Hub(strict=settings.app_env in (AppEnv.DEV, AppEnv.TEST))
        self.presence = Presence(redis, clock)
        self.locks = RedisLocks(redis, clock)
        self.cells = CellLocks(self.locks, clock)
        self.allowed_hosts = allowed_origin_hosts(settings)
        self.revalidate_seconds = REVALIDATE_SECONDS
        self.sweep_seconds: float = SWEEP_SECONDS
        self.listener = Listener(
            settings.redis_url.get_secret_value(),
            on_event=self.on_event,
            on_control=self.on_control,
            on_reconnect=self.on_reconnect,
        )
        self._previous_bus: EventBus | None = None
        self._previous_checker: LockChecker | None = None
        self._sweeper: asyncio.Task[None] | None = None

    def session_service(self) -> SessionService:
        return SessionService(self.redis, self.clock)

    # --- жизненный цикл ---

    async def start(self, *, wait_ready: float = 5.0) -> None:
        self._previous_bus = set_bus(RedisBus(self.redis))
        self._previous_checker = set_lock_checker(RedisLockChecker(self.locks))
        add_session_ended_listener(self.on_session_ended)
        self.listener.start()
        self._sweeper = asyncio.create_task(self._sweep_loop(), name="rt-presence-sweep")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.listener.ready.wait(), timeout=wait_ready)

    async def stop(self) -> None:
        self.hub.close_all(CLOSE_RESTART, "server restart")
        await asyncio.sleep(0)  # писатели соединений успевают отправить закрытие
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
            self._sweeper = None
        await self.listener.stop()
        with contextlib.suppress(ValueError):
            remove_session_ended_listener(self.on_session_ended)
        if self._previous_bus is not None:
            set_bus(self._previous_bus)
            self._previous_bus = None
        if self._previous_checker is not None:
            set_lock_checker(self._previous_checker)
            self._previous_checker = None

    # --- входящие из Redis ---

    async def on_event(self, event: dict[str, Any]) -> None:
        if event.get("event") == "member.updated":
            self._recheck_members(event)
        self.hub.dispatch(event)
        # захваты: сохранение поля автором снимает захват, перехват — забыть свой (RT-005)
        await self.cells.on_event(self.hub, event)

    def _recheck_members(self, event: dict[str, Any]) -> None:
        channel = str(event.get("channel", ""))
        try:
            project_id = uuid.UUID(channel.split(":")[1])
        except (IndexError, ValueError):
            return
        users = {str(u) for u in event.get("data", {}).get("user_ids", [])}
        for conn in self.hub.in_project(project_id):
            if str(conn.user_id) in users:
                conn.recheck.set()

    def on_control(self, message: dict[str, Any]) -> None:
        if message.get("kind") == CONTROL_SESSION_ENDED:
            try:
                hashed = bytes.fromhex(str(message["session_hash"]))
            except (KeyError, ValueError):
                return
            for conn in self.hub.by_session(hashed):
                end_connection(conn, str(message.get("reason") or "revoked"))

    def on_reconnect(self) -> None:
        """Связь с Redis восстановлена: события за обрыв потеряны — пусть клиенты догонят."""
        log.warning("rt_listener_reconnected", connections=len(self.hub.connections))
        self.hub.close_all(CLOSE_RESTART, "event stream restarted")

    async def on_session_ended(self, event: SessionEnded) -> None:
        """Хук AUTH-002 (после commit): разослать завершение сессии всем экземплярам."""
        await publish_control(self.redis, session_ended_message(event))

    # --- присутствие ---

    def _local_presence(self) -> dict[uuid.UUID, dict[str, dict[str, Any]]]:
        local: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
        for conn in self.hub.connections.values():
            for project_id in conn.projects:
                local.setdefault(project_id, {})[conn.id] = conn.user
        return local

    async def sweep_presence(self) -> None:
        await self.presence.sweep(self._local_presence().items())

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_seconds)
            try:
                await self.sweep_presence()
            except Exception:  # Redis недоступен: следующий круг
                log.exception("presence_sweep_failed")
