"""AUTH-016: отзыв доступа и синхронизация с AD (FR-AUTH-AD-08, Q-18, TC-AUTH-02, G-26) — на
имитации AD."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_sync
from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import SessionService
from estimator.db.enums import (
    RoleSource,
    SystemRole,
    UserBlockReason,
    UserSource,
    UserStatus,
)
from estimator.db.models.users import User, UserRole, UserSession
from estimator.jobs.schedule import build_beat_schedule
from tests.integration.auth.conftest import complete_setup
from tests.support import fake_ad as support
from tests.support.fake_ad import FakeDirectory, Person

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-AD-08")]


async def _ad_user(db: AsyncSession, person: Person) -> User:
    user = User(login=person.entry.login, full_name=person.entry.full_name, source=UserSource.AD,
                ad_object_guid=person.entry.object_guid, status=UserStatus.ACTIVE)  # fmt: skip
    db.add(user)
    await db.flush()
    return user


async def _session(db: AsyncSession, redis: Redis, user: User) -> str:
    sid, _record = await SessionService(redis).create(
        db, user.id, [], SessionPolicy(), ip="10.1.2.3", mfa_passed=True
    )
    return sid


async def _open_sessions(db: AsyncSession, user: User) -> int:
    rows = await db.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .execution_options(populate_existing=True)
    )  # fmt: skip
    return len(rows.all())


async def _state(db: AsyncSession, user: User) -> tuple[UserStatus, UserBlockReason | None]:
    await db.refresh(user)
    return user.status, user.block_reason


async def _summaries(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = 'users.ad_sync.completed' "
        "ORDER BY id"))  # fmt: skip
    return [{k: v for k, v in r[0].items() if k != "actor"} for r in rows]


@pytest.fixture(autouse=True)
def state_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свой ключ состояния у каждого теста: Redis общий для процессов xdist и других тестов."""
    monkeypatch.setattr(ad_sync, "STATE_KEY", f"test:{uuid.uuid4().hex[:8]}:{ad_sync.STATE_KEY}")


@pytest.fixture
async def ad(
    db_session: AsyncSession, fake_ad: FakeDirectory, encryption_key: None
) -> FakeDirectory:
    await complete_setup(db_session)
    await support.configure(db_session, mapping=[(support.MODERATORS, "moderator")])
    return fake_ad


@pytest.mark.spec("TC-AUTH-02")
async def test_sessions_check_blocks_and_daily_unblocks(
    db_session: AsyncSession, redis_client: Redis, ad: FakeDirectory
) -> None:
    online = ad.add("online")
    offline = ad.add("offline")
    manual = ad.add("manual")
    u_online, u_offline, u_manual = [
        await _ad_user(db_session, p) for p in (online, offline, manual)
    ]
    sid = await _session(db_session, redis_client, u_online)
    u_manual.status, u_manual.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db_session.flush()

    ad.update(online, disabled=True)
    ad.remove(offline)
    summary = await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert (summary.checked, summary.blocked) == (1, 1), "15 минут — только с активными сессиями"
    assert await _state(db_session, u_online) == (UserStatus.BLOCKED, UserBlockReason.AD_DISABLED)
    assert await _open_sessions(db_session, u_online) == 0
    assert (await SessionService(redis_client).load(sid)).record is None, "сессия завершена сразу"
    assert await _state(db_session, u_offline) == (UserStatus.ACTIVE, None)

    daily = await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    assert daily.checked == 3
    assert await _state(db_session, u_offline) == (UserStatus.BLOCKED, UserBlockReason.AD_MISSING)

    ad.update(online, disabled=False)
    ad.people[manual.entry.dn].groups = {support.ACCESS}
    again = await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    assert again.unblocked == 1
    assert await _state(db_session, u_online) == (UserStatus.ACTIVE, None), "причина ушла — снято"
    assert await _state(db_session, u_manual) == (UserStatus.BLOCKED, UserBlockReason.MANUAL)
    assert (await _summaries(db_session))[0] == {
        "kind": "sessions_15min", "checked": 1, "blocked": 1, "unblocked": 0,
        "roles_changed": 0, "skipped_ad_unavailable": False,
    }  # fmt: skip


@pytest.mark.spec("G-26")
async def test_ad_unavailable_changes_nothing(
    db_session: AsyncSession, redis_client: Redis, ad: FakeDirectory
) -> None:
    person = ad.add("someone")
    user = await _ad_user(db_session, person)
    await _session(db_session, redis_client, user)
    ad.remove(person)
    ad.available = False
    summary = await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert summary.skipped_ad_unavailable
    assert await _state(db_session, user) == (UserStatus.ACTIVE, None)
    assert await _open_sessions(db_session, user) == 1, "AD недоступен — сессии не трогаем"
    state = await ad_sync.last_state(redis_client)
    assert state[ad_sync.SESSIONS]["ok"] is False


async def test_daily_refreshes_attributes_and_roles(
    db_session: AsyncSession, redis_client: Redis, ad: FakeDirectory
) -> None:
    person = ad.add("lead", groups=(support.ACCESS, support.MODERATORS))
    user = await _ad_user(db_session, person)
    ad.update(person, full_name="Новая Фамилия")
    summary = await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    assert summary.roles_changed == 1
    await db_session.refresh(user)
    assert user.full_name == "Новая Фамилия"
    role = await db_session.scalar(select(UserRole).where(UserRole.user_id == user.id))
    assert role is not None
    assert (role.role, role.source) == (SystemRole.MODERATOR, RoleSource.AD_GROUP)


@pytest.mark.usefixtures("encryption_key")
async def test_local_mode_does_nothing(
    db_session: AsyncSession, redis_client: Redis, fake_ad: FakeDirectory
) -> None:
    await support.configure(db_session, mode="local")
    summary = await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    assert summary == replace(summary, checked=0)
    assert fake_ad.calls == []


def test_schedule_registered() -> None:
    schedule = build_beat_schedule()
    assert schedule["ad_sync_sessions"]["task"] == "estimator.auth.ad_sync.sessions"
    assert schedule["ad_sync_daily"]["task"] == "estimator.auth.ad_sync.daily"
