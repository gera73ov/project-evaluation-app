"""NTF-004 (пачка за 15 минут) и NTF-005 (ежедневная сводка): FR-NOTIF-02, Q-45, FR-NOTIF-03."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.users import User
from estimator.jobs.schedule import build_beat_schedule
from estimator.notifications import batches, digest, tasks
from estimator.notifications.mail import render_email
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.helpers import create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-NOTIF-02")]

SERVER = {
    "host": "smtp.corp", "port": 587, "security": "starttls", "username": None,
    "from_address": "robot@corp.ru", "from_name": "Оценка проектов", "timeout_seconds": 10,
}  # fmt: skip
SECRET_TITLE = "Модуль биллинга"


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


async def _setup(world: World, db: AsyncSession) -> tuple[User, uuid.UUID]:
    await set_setting(db, "smtp.server", SERVER)
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    actor = await world.actor()
    user = await db.get(User, actor.id)
    assert user is not None
    user.email = f"e-{uuid.uuid4().hex[:8]}@corp.ru"
    await db.flush()
    return user, pid


async def _note(db: AsyncSession, user: User, pid: uuid.UUID, kind: str,
                at: dt.datetime) -> None:  # fmt: skip
    db.add(Notification(user_id=user.id, project_id=pid, kind=kind, created_at=at,
                        payload={"project_id": str(pid), "title": SECRET_TITLE}))  # fmt: skip
    await db.flush()


def _mine(mails: list[tuple[Any, ...]], kind: str, user: User) -> list[dict[str, Any]]:
    return [m[2] for m in mails if m[0] == kind and m[1] == user.email]


@pytest.mark.spec("Q-45")
@pytest.mark.spec("FR-NOTIF-03")
async def test_three_events_one_letter(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    user, pid = await _setup(world, db_session)
    t0 = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    for minutes, kind in ((0, batches.QUESTION), (4, batches.ANSWER), (9, batches.QUESTION)):
        await _note(db_session, user, pid, kind, t0 + dt.timedelta(minutes=minutes))

    assert await batches.flush_due(db_session, t0 + dt.timedelta(minutes=10)) == 0, "окно открыто"
    sent = await batches.flush_due(db_session, t0 + dt.timedelta(minutes=15))
    await deliver_events(db_session)
    assert sent >= 1
    [letter] = _mine(mails, batches.KIND, user)
    [item] = letter["projects"]
    assert (item["project_name"], item["questions"], item["answers"]) == ("Портал дилеров", 2, 1)
    assert item["link"].endswith(f"/projects/{pid}")
    rendered = render_email(batches.KIND, letter)
    assert "«Портал дилеров»: 2 вопроса вам, 1 ответ на ваш вопрос" in rendered.subject
    assert SECRET_TITLE not in rendered.text + rendered.html, "без названий узлов и текста"

    assert await batches.flush_due(db_session, t0 + dt.timedelta(minutes=30)) == 0
    await deliver_events(db_session)
    assert len(_mine(mails, batches.KIND, user)) == 1, "отправленное не уходит повторно"


async def test_batch_opt_out_and_no_smtp(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    user, pid = await _setup(world, db_session)
    t0 = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    await _note(db_session, user, pid, batches.ANSWER, t0)
    user.notify_questions = False
    await db_session.flush()
    await batches.flush_due(db_session, t0 + dt.timedelta(minutes=20))
    await deliver_events(db_session)
    assert _mine(mails, batches.KIND, user) == [], "отключено в профиле — писем нет"

    user.notify_questions = True
    await set_setting(db_session, "smtp.server", {**SERVER, "host": None})
    assert await batches.flush_due(db_session, t0 + dt.timedelta(minutes=20)) == 0


async def test_digest_only_with_new_events(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    user, pid = await _setup(world, db_session)
    await set_setting(db_session, "digest.time", "09:00")
    slot = await digest.slot(db_session, dt.datetime.now(dt.UTC))
    after = slot + dt.timedelta(minutes=3)

    assert await digest.send_due(db_session, slot - dt.timedelta(minutes=1)) == 0, "рано"
    await digest.send_due(db_session, after)
    await deliver_events(db_session)
    assert _mine(mails, digest.KIND, user) == [], "без новых событий письма нет"

    await _note(db_session, user, pid, "moderator_change", slot - dt.timedelta(hours=2))
    await _note(db_session, user, pid, batches.QUESTION, slot - dt.timedelta(hours=1))
    await _note(db_session, user, pid, "assigned_to_project", slot - dt.timedelta(hours=1))
    await digest.send_due(db_session, after)
    await deliver_events(db_session)
    [letter] = _mine(mails, digest.KIND, user)
    assert letter["total"] == 2, "служебные уведомления в сводку не входят"
    [item] = letter["projects"]
    assert item["counters"] == {"moderator_change": 1, batches.QUESTION: 1}
    assert SECRET_TITLE not in render_email(digest.KIND, letter).text
    await db_session.refresh(user)
    assert user.last_digest_at == after

    await _note(db_session, user, pid, "branch_back_to_draft", after + dt.timedelta(minutes=1))
    await digest.send_due(db_session, after + dt.timedelta(minutes=5))
    await deliver_events(db_session)
    assert len(_mine(mails, digest.KIND, user)) == 1, "второй сводки за день нет"
    tomorrow = after + dt.timedelta(days=1)
    await digest.send_due(db_session, tomorrow)
    await deliver_events(db_session)
    assert _mine(mails, digest.KIND, user)[-1]["total"] == 1, "только новое с прошлой сводки"

    user.notify_digest = False
    await _note(db_session, user, pid, "moderator_change", tomorrow + dt.timedelta(minutes=1))
    await digest.send_due(db_session, tomorrow + dt.timedelta(days=1))
    await deliver_events(db_session)
    assert len(_mine(mails, digest.KIND, user)) == 2, "отключено в профиле"


def test_periodic_tasks_registered() -> None:
    schedule = build_beat_schedule()
    assert schedule["notifications_questions_batch"]["task"] == tasks.BATCH_TASK
    assert schedule["notifications_digest"]["task"] == tasks.DIGEST_TASK
