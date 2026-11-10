"""NTF-007: удаление уведомлений старше срока хранения (NFR-REL-06, ``retention.periods``)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.discussions import Notification
from estimator.jobs.schedule import build_beat_schedule
from estimator.notifications import tasks
from tests.integration.auth.conftest import set_setting
from tests.integration.auth.helpers import make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-REL-06")]


async def _count(db: AsyncSession, user_id: object) -> int:
    query = select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
    return int(await db.scalar(query) or 0)


async def test_purge_uses_retention_setting(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    now = dt.datetime.now(dt.UTC)
    for age in (400, 200, 10):
        db_session.add(Notification(user_id=user.id, kind="assigned",
                                    created_at=now - dt.timedelta(days=age)))  # fmt: skip
    await db_session.flush()

    await set_setting(db_session, "retention.periods", {})
    assert await tasks.retention_days(db_session) == 365
    assert await tasks.purge_old(db_session, now) >= 1
    assert await _count(db_session, user.id) == 2

    await set_setting(db_session, "retention.periods", {"notifications_days": 30})
    await tasks.purge_old(db_session, now)
    assert await _count(db_session, user.id) == 1, "осталось только свежее"


def test_purge_is_scheduled_nightly() -> None:
    entry = build_beat_schedule()["notifications_purge"]
    assert entry["task"] == tasks.PURGE_TASK
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({3}, {40})
