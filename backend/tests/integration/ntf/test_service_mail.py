"""NTF-006: служебное письмо «Вас назначили» (FR-NOTIF-02, BR-PRJ-01, FR-NOTIF-03, TC-NOTIF-01).

В «Подготовке» письма нет; при переходе в «Оценку» — письмо каждому назначенному с адресом,
только название и ссылка; без SMTP письма не ставятся.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.users import User
from estimator.notifications import tasks as mail_tasks
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.helpers import create_project, discipline

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-NOTIF-02"),
              pytest.mark.spec("BR-PRJ-01")]  # fmt: skip

SERVER = {
    "host": "smtp.corp", "port": 587, "security": "starttls", "username": None,
    "from_address": "robot@corp.ru", "from_name": "Оценка проектов", "timeout_seconds": 10,
}  # fmt: skip


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


async def _team(world: World, db: AsyncSession) -> tuple[Actor, uuid.UUID, Actor, str]:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db, "Бэкенд")
    added = await moderator.post(f"/projects/{pid}/disciplines",
                                 json={"discipline_id": str(backend)})  # fmt: skip
    assert added.status_code == 201, added.text
    expert = await world.actor()
    user = await db.get(User, expert.id)
    assert user is not None
    user.email = f"e-{uuid.uuid4().hex[:8]}@corp.ru"
    await db.flush()
    team = {"members": [
        {"user_id": str(moderator.id), "role": "moderator"},
        {"user_id": str(expert.id), "role": "expert", "discipline_id": str(backend)},
    ]}  # fmt: skip
    assert (await moderator.put(f"/projects/{pid}/members", json=team)).status_code == 200
    return moderator, pid, expert, user.email


async def _note(db: AsyncSession, user_id: uuid.UUID) -> Notification:
    return (await db.scalars(select(Notification).where(
        Notification.user_id == user_id, Notification.kind == "assigned_to_project",
    ))).one()  # fmt: skip


@pytest.mark.spec("FR-NOTIF-03")
@pytest.mark.tc("TC-NOTIF-01")
async def test_assigned_mail_on_launch(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    await set_setting(db_session, "smtp.server", SERVER)
    moderator, pid, expert, email = await _team(world, db_session)
    await deliver_events(db_session)
    assert [m for m in mails if m[0] == "assigned_to_project"] == [], "в «Подготовке» письма нет"

    launched = await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    assert launched.status_code == 200, launched.text
    await deliver_events(db_session)
    [letter] = [m for m in mails if m[0] == "assigned_to_project"]
    _kind, address, fields, override = letter
    assert address == email
    assert fields["project_name"] == "Портал дилеров"
    assert fields["link"].endswith(f"/projects/{pid}")
    assert set(fields) == {"project_name", "link"}, "без дедлайна и подробностей"
    assert override is None
    assert (await _note(db_session, expert.id)).emailed_at is not None


async def test_no_mail_without_smtp(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    moderator, pid, expert, _email = await _team(world, db_session)
    launched = await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    assert launched.status_code == 200, launched.text
    await deliver_events(db_session)
    assert [m for m in mails if m[0] == "assigned_to_project"] == []
    assert (await _note(db_session, expert.id)).emailed_at is None
