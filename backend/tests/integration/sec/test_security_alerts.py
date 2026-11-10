"""SEC-011: оповещения ИБ (SEC-AUTH-07, Q-26; TC-AUTH-06).

Письмо уходит всем активным администраторам с почтой и на ``security.alert_email``. При смене
SMTP — сначала через старый сервер, затем через новый; не ушло — ``system.alert.delivery_failed``
и отметка «Состояния системы», изменение не отменяется.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from estimator.db.enums import SystemRole, UserStatus
from estimator.notifications import tasks as mail_tasks
from estimator.security import audit
from estimator.security.alerts import notify
from estimator.security.alerts import tasks as alert_tasks
from tests.integration.auth.conftest import set_setting
from tests.integration.auth.helpers import make_user
from tests.support.smtp_sink import SmtpSink

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUTH-07")]

OLD_SERVER = {
    "host": "smtp-old.corp",
    "port": 25,
    "security": "none",
    "username": None,
    "from_address": "robot@corp.ru",
    "from_name": "Оценка",
    "timeout_seconds": 5,
}


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


async def _admin(db: AsyncSession, *, status: UserStatus = UserStatus.ACTIVE,
                 email: bool = True, role: SystemRole = SystemRole.ADMIN) -> str:  # fmt: skip
    user = await make_user(db, role, status=status)
    user.email = f"{user.login}@corp.ru" if email else None
    await db.flush()
    return user.email or ""


@pytest.mark.spec("Q-26")
async def test_alert_goes_to_active_admins_and_security_address(
    db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    ib = f"ib-{uuid.uuid4().hex[:6]}@corp.ru"
    await set_setting(db_session, "security.alert_email", ib)
    admin = await _admin(db_session)
    blocked = await _admin(db_session, status=UserStatus.BLOCKED)
    moderator = await _admin(db_session, role=SystemRole.MODERATOR)
    await _admin(db_session, email=False)

    count = await notify.dispatch(
        db_session, "superadmin_login_failures", time="10.11.2026 09:00 UTC",
        actor_login="root", ip="10.0.0.5",
    )  # fmt: skip
    addresses = [m[1] for m in mails]
    assert count == len(mails)
    assert addresses[0] == ib
    assert admin in addresses
    assert blocked not in addresses
    assert moderator not in addresses
    kind, _, fields, override = mails[0]
    assert (kind, override) == ("security_alert", None)
    assert fields["alert"] == "superadmin_login_failures"
    assert fields["link"].endswith("/audit")


async def test_listener_queues_alert_after_commit(
    db_engine: AsyncEngine, alerts_queue: list[tuple[Any, ...]]
) -> None:
    from estimator.db.session import transaction

    notify.install()
    notify.install()  # повторная установка не дублирует письма
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with transaction(maker) as session:
        await audit.write(
            session,
            "auth.password.reset_issued",
            login="root",
            ip="10.0.0.7",
            object_type="user",
            details={"target_roles": ["admin"], "delivery": "screen"},
        )  # fmt: skip — условие из контракта: сброс пароля администратору
        await audit.write(
            session,
            "auth.password.reset_issued",
            object_type="user",
            details={"target_roles": ["moderator"], "delivery": "email"},
        )  # fmt: skip — без оповещения
        await audit.write(
            session, "system.settings.changed", object_type="setting",
            details={"section": "smtp", "changes": {"host": ["a", "b"]}},
        )  # fmt: skip
    assert [(c[0], c[2], c[3], c[4]) for c in alerts_queue] == [
        ("privileged_password_reset", "root", "10.0.0.7", None),
        ("smtp_changed", None, None, notify.NEW_SMTP),
    ]


@pytest.mark.spec("TC-AUTH-06")
async def test_smtp_change_alerts_through_old_server_first(
    db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    await set_setting(db_session, "smtp.server", OLD_SERVER)
    await set_setting(db_session, "smtp.password", {"enc": "c2VjcmV0", "kid": "k1"})
    admin = await _admin(db_session)
    count = await notify.before_smtp_change(db_session, actor_login="root", ip="10.0.0.9")
    assert count == len(mails) > 0
    mine = next(m for m in mails if m[1] == admin)
    assert mine[2]["alert"] == "smtp_changed"
    assert mine[3] == {"server": OLD_SERVER, "password": {"enc": "c2VjcmV0", "kid": "k1"}}
    assert mine[4] == notify.OLD_SMTP

    await set_setting(db_session, "smtp.server", {**OLD_SERVER, "host": None})
    mails.clear()
    assert await notify.before_smtp_change(db_session, actor_login=None, ip=None) == 0
    assert mails == []


@pytest.mark.spec("TC-AUTH-06")
@pytest.mark.parametrize("failure", ["permanent", "not_configured"])
def test_failed_alert_email_is_recorded(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(alert_tasks, "record_undelivered", lambda *a: recorded.append(a))
    fields = {"alert": "smtp_changed", "time": "t", "actor_login": None, "ip": None,
              "link": "https://est/audit"}  # fmt: skip
    with SmtpSink() as sink:
        sink.fail_codes = [550]
        server = {**OLD_SERVER, "host": "127.0.0.1" if failure == "permanent" else None,
                  "port": sink.port}  # fmt: skip
        mail_tasks.send_email.apply(
            args=("security_alert", "ib@corp.ru", fields, {"server": server, "password": None},
                  notify.OLD_SMTP),
        )  # fmt: skip
        # обычное письмо без канала оповещения отметок не делает
        mail_tasks.send_email.apply(
            args=("security_alert", "ib@corp.ru", fields, {"server": server, "password": None})
        )
    assert recorded == [("smtp_changed", notify.OLD_SMTP)]


@pytest.mark.spec("TC-AUTH-06")
async def test_undelivered_is_audited_and_shown_in_health(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    await redis_client.delete(notify.UNDELIVERED_KEY)
    assert await notify.last_undelivered(redis_client) is None
    await notify.record_undelivered(db_session, redis_client, "smtp_changed", notify.OLD_SMTP)
    rows = await db_session.execute(text(
        "SELECT result, details FROM audit.audit_log "
        "WHERE event_type = 'system.alert.delivery_failed' ORDER BY id DESC LIMIT 1"
    ))  # fmt: skip
    result, details = rows.one()
    assert (str(result), details) == (
        "failure",
        {"alert_type": "smtp_changed", "channel": "old_smtp", "actor": "system"},
    )
    mark = await notify.last_undelivered(redis_client)
    assert mark is not None
    assert (mark["alert_type"], mark["channel"]) == ("smtp_changed", "old_smtp")

    class Broken:
        async def set(self, *_: Any, **__: Any) -> None:
            raise ConnectionError("redis down")

    await notify.record_undelivered(db_session, Broken(), "smtp_changed", notify.NEW_SMTP)  # type: ignore[arg-type]
    await notify.record_undelivered(db_session, None, "smtp_changed", notify.NEW_SMTP)


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch, test_database_url: str) -> None:
    """Задачи Celery открывают своё подключение по настройкам процесса — на тестовую базу."""
    import os

    from estimator.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    get_settings.cache_clear()


def test_worker_task_dispatches(worker_env: None, mails: list[tuple[Any, ...]]) -> None:
    count = alert_tasks.notify_alert.apply(
        args=("audit_chain_broken", "10.11.2026 04:00 UTC", None, None)
    ).get()
    assert count == len(mails)
    assert all(m[2]["alert"] == "audit_chain_broken" for m in mails)


@pytest.mark.spec("TC-AUTH-06")
def test_worker_records_undelivered(worker_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake(_db: Any, _redis: Any, alert_type: str, channel: str) -> None:
        calls.append((alert_type, channel))

    monkeypatch.setattr(notify, "record_undelivered", fake)
    alert_tasks.record_undelivered("smtp_changed", notify.NEW_SMTP)
    assert calls == [("smtp_changed", notify.NEW_SMTP)]

    async def broken(*_: Any) -> None:
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(notify, "record_undelivered", broken)
    alert_tasks.record_undelivered("smtp_changed", notify.NEW_SMTP)  # сбой — только в лог


def test_enqueue_publishes_without_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        alert_tasks.notify_alert, "apply_async", lambda args, **kw: sent.append((args, kw))
    )
    alert_tasks.publish("smtp_changed", "t", "root", "10.0.0.1", notify.NEW_SMTP)
    assert sent == [(("smtp_changed", "t", "root", "10.0.0.1", "new_smtp"), {"retry": False})]
