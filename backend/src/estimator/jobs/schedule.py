"""Реестр периодических задач и защита от двойного запуска beat (INF-008).

Трек добавляет свою задачу вызовом :func:`register_periodic` в своём модуле ``tasks.py``
(модуль должен быть в ``TASK_MODULES``) или строкой в :data:`_DEFAULTS`. Время в ``crontab`` —
в часовом поясе приложения (FR-UI-02): например, ``crontab(hour=3, minute=0)`` для
ежедневной синхронизации AD в 03:00 (FR-AUTH-AD-08).

Двойной запуск beat даёт двойные письма и задачи, поэтому :class:`LockedScheduler` держит
блокировку в Redis: второй экземпляр не стартует, а потерявший блокировку — останавливается.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from celery.beat import PersistentScheduler
from celery.schedules import crontab, schedule
from redis import Redis
from redis.exceptions import LockError

from estimator.logging import get_logger

log = get_logger(__name__)

BEAT_LOCK_KEY = "estimator:beat:lock"
BEAT_LOCK_TTL = 60.0


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    task: str
    when: crontab | schedule
    queue: str | None = None
    kwargs: dict[str, Any] | None = None


_registry: dict[str, PeriodicTask] = {}

_DEFAULTS = (PeriodicTask("heartbeat", "estimator.jobs.heartbeat", crontab()),)


def register_periodic(item: PeriodicTask) -> None:
    """Добавить периодическую задачу. Имя уникально: повтор — ошибка, а не тихая замена."""
    if item.name in _registry:
        raise ValueError(f"периодическая задача «{item.name}» уже зарегистрирована")
    _registry[item.name] = item


def unregister_periodic(name: str) -> None:
    _registry.pop(name, None)


for _item in _DEFAULTS:
    register_periodic(_item)


def build_beat_schedule() -> dict[str, dict[str, Any]]:
    """Расписание в формате ``beat_schedule`` Celery."""
    result: dict[str, dict[str, Any]] = {}
    for item in _registry.values():
        entry: dict[str, Any] = {"task": item.task, "schedule": item.when}
        if item.queue:
            entry["options"] = {"queue": item.queue}
        if item.kwargs:
            entry["kwargs"] = item.kwargs
        result[item.name] = entry
    return result


class BeatLock:
    """Блокировка «один beat на стенд» в Redis с продлением."""

    def __init__(self, client: Redis, ttl: float = BEAT_LOCK_TTL) -> None:
        self.ttl = ttl
        self.owner = str(uuid.uuid4())
        self._lock = client.lock(BEAT_LOCK_KEY, timeout=ttl, blocking=False, thread_local=False)
        self._refreshed = 0.0

    def acquire(self) -> bool:
        ok = bool(self._lock.acquire(token=self.owner))
        if ok:
            self._refreshed = time.monotonic()
        return ok

    def refresh_if_due(self) -> None:
        """Продлить блокировку, если прошла треть TTL. Потеря блокировки — ``LockError``."""
        if time.monotonic() - self._refreshed >= self.ttl / 3:
            self._lock.reacquire()
            self._refreshed = time.monotonic()

    def release(self) -> None:
        try:
            self._lock.release()
        except LockError:
            log.warning("beat_lock_release_failed")


class BeatAlreadyRunningError(RuntimeError):
    pass


class LockedScheduler(PersistentScheduler):
    """Планировщик beat, который работает, только пока держит :class:`BeatLock`."""

    lock: BeatLock | None = None

    def setup_schedule(self) -> None:
        client = Redis.from_url(self.app.conf.broker_url)
        self.lock = BeatLock(client)
        if not self.lock.acquire():
            log.error("beat_already_running", lock_key=BEAT_LOCK_KEY)
            raise BeatAlreadyRunningError("другой экземпляр beat уже держит блокировку")
        log.info("beat_lock_acquired", owner=self.lock.owner)
        super().setup_schedule()

    def tick(self, *args: Any, **kwargs: Any) -> float:
        if self.lock is None:  # setup_schedule ещё не вызывался
            return super().tick(*args, **kwargs)
        try:
            self.lock.refresh_if_due()
        except LockError as exc:
            log.critical("beat_lock_lost", owner=self.lock.owner)
            raise SystemExit(1) from exc
        return min(super().tick(*args, **kwargs), self.lock.ttl / 3)

    def close(self) -> None:
        super().close()
        if self.lock is not None:
            self.lock.release()
