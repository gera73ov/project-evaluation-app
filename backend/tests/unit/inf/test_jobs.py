"""INF-008: Celery, расписания в поясе приложения, один beat (SPEC 13.1, FR-UI-02)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from zoneinfo import ZoneInfo

import pytest
from celery.contrib.testing.worker import start_worker
from celery.schedules import crontab
from redis.exceptions import LockError, LockNotOwnedError

from estimator.config import Settings
from estimator.jobs import schedule as sched
from estimator.jobs.celery_app import make_celery, queue_lengths


def test_config_from_settings() -> None:
    app = make_celery(Settings(app_timezone="Asia/Yekaterinburg"))
    assert app.conf.timezone == "Asia/Yekaterinburg"
    assert app.conf.task_default_queue == "default"
    assert app.conf.accept_content == ["json"]
    assert "heartbeat" in app.conf.beat_schedule


def test_worker_executes_task() -> None:
    app = make_celery(Settings(celery_broker_url="memory://"))
    app.conf.result_backend = "cache+memory://"
    app.conf.task_ignore_result = False
    with start_worker(app, perform_ping_check=False, loglevel="WARNING"):
        result = app.send_task("estimator.jobs.ping")
        assert result.get(timeout=10) == "pong"


def test_heartbeat_task_logs() -> None:
    from estimator.jobs.builtin import heartbeat

    heartbeat.run()


@pytest.mark.spec("FR-UI-02")
def test_crontab_runs_in_app_timezone() -> None:
    """Задача «в 03:00» срабатывает в 03:00 по поясу приложения, а не по UTC."""
    app = make_celery(Settings(app_timezone="Asia/Novosibirsk"))  # UTC+7
    tz = ZoneInfo("Asia/Novosibirsk")
    now_local = datetime(2026, 11, 6, 2, 59, tzinfo=tz)
    job = crontab(hour=3, minute=0, app=app, nowfun=lambda: now_local)
    last_run = datetime(2026, 11, 5, 3, 0, tzinfo=tz)
    remaining = job.remaining_estimate(last_run)
    fire_at = (now_local + remaining).astimezone(UTC)
    assert fire_at == datetime(2026, 11, 5, 20, 0, tzinfo=UTC)  # 03:00 Новосибирск
    assert remaining == timedelta(minutes=1)
    assert not job.is_due(last_run).is_due

    later = lambda: datetime(2026, 11, 6, 3, 0, 30, tzinfo=tz)  # noqa: E731
    assert crontab(hour=3, minute=0, app=app, nowfun=later).is_due(last_run).is_due


def test_registry() -> None:
    item = sched.PeriodicTask(
        "t-daily", "estimator.jobs.ping", crontab(hour=4), "default", {"a": 1}
    )
    sched.register_periodic(item)
    try:
        with pytest.raises(ValueError, match="уже зарегистрирована"):
            sched.register_periodic(item)
        entry = sched.build_beat_schedule()["t-daily"]
        assert entry["options"] == {"queue": "default"}
        assert entry["kwargs"] == {"a": 1}
    finally:
        sched.unregister_periodic("t-daily")
    assert "t-daily" not in sched.build_beat_schedule()


class FakeLock:
    holders: ClassVar[dict[str, str]] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self.token: str | None = None

    def acquire(self, token: str) -> bool:
        if self.name in self.holders:
            return False
        self.holders[self.name] = token
        self.token = token
        return True

    def reacquire(self) -> None:
        if self.holders.get(self.name) != self.token:
            raise LockNotOwnedError("lost")

    def release(self) -> None:
        if self.holders.get(self.name) != self.token:
            raise LockNotOwnedError("not owned")
        del self.holders[self.name]


class FakeRedis:
    def lock(self, name: str, **_kwargs: object) -> FakeLock:
        return FakeLock(name)


@pytest.fixture(autouse=True)
def _clean_locks():
    FakeLock.holders.clear()
    yield
    FakeLock.holders.clear()


def test_second_beat_cannot_take_lock() -> None:
    first, second = sched.BeatLock(FakeRedis()), sched.BeatLock(FakeRedis())
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()


def test_lock_refresh_and_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = sched.BeatLock(FakeRedis(), ttl=30)
    assert lock.acquire()
    lock.refresh_if_due()  # рано — ничего не делает
    monkeypatch.setattr(sched.time, "monotonic", lambda: 10**9)
    lock.refresh_if_due()  # продлевает
    FakeLock.holders[sched.BEAT_LOCK_KEY] = "someone-else"
    lock._refreshed = 0
    with pytest.raises(LockError):
        lock.refresh_if_due()
    lock.release()  # чужую блокировку не снимает и не падает


def _scheduler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> type[sched.LockedScheduler]:
    monkeypatch.setattr(sched.Redis, "from_url", staticmethod(lambda _url: FakeRedis()))
    return sched.LockedScheduler


def test_locked_scheduler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cls = _scheduler(monkeypatch, tmp_path)
    app = make_celery(Settings(celery_broker_url="memory://"))
    s1 = cls(app=app, schedule_filename=str(tmp_path / "s1"), lazy=False)
    assert s1.lock is not None
    assert s1.tick() <= s1.lock.ttl / 3
    with pytest.raises(sched.BeatAlreadyRunningError):
        cls(app=app, schedule_filename=str(tmp_path / "s2"), lazy=False)
    FakeLock.holders[sched.BEAT_LOCK_KEY] = "someone-else"
    s1.lock._refreshed = -(10**9)
    with pytest.raises(SystemExit):
        s1.tick()
    FakeLock.holders[sched.BEAT_LOCK_KEY] = s1.lock.owner
    s1.close()
    assert sched.BEAT_LOCK_KEY not in FakeLock.holders


def test_scheduler_tick_before_setup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cls = _scheduler(monkeypatch, tmp_path)
    app = make_celery(Settings(celery_broker_url="memory://"))
    s = cls(app=app, schedule_filename=str(tmp_path / "s3"), lazy=False)
    lock, s.lock = s.lock, None
    assert s.tick() >= 0  # без блокировки — обычный тик PersistentScheduler
    s.close()
    lock.release()


def test_queue_lengths(monkeypatch: pytest.MonkeyPatch) -> None:
    class R:
        def llen(self, name: str) -> int:
            return {"default": 5}[name]

        def close(self) -> None:
            pass

    monkeypatch.setattr("estimator.jobs.celery_app.Redis.from_url", lambda *a, **k: R())
    assert queue_lengths(Settings()) == {"default": 5}


def test_app_factory_registers_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    import estimator.main as main

    monkeypatch.setattr(main, "_metrics_registered", False)
    registered = []
    monkeypatch.setattr(main.REGISTRY, "register", registered.append)
    main.app_factory()
    main.register_metrics(Settings())
    # очереди Celery и очередь SIEM (SEC-012), по одному разу
    assert [type(c).__name__ for c in registered] == ["QueueLengthCollector", "QueueCollector"]
