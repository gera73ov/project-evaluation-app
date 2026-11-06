"""AUTH-002: серверные сессии в Redis и строки sessions."""

from __future__ import annotations

import time
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import PRE_MFA_SECONDS, SessionPolicy
from estimator.auth.sessions import (
    ExpiryReason,
    RevokeReason,
    SessionEnded,
    SessionService,
    add_session_ended_listener,
    id_hash,
    remove_session_ended_listener,
)
from estimator.db.enums import SystemRole
from estimator.db.models.users import UserSession
from estimator.db.session import run_after_commit
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SESS-01")]

POLICY = SessionPolicy()


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(redis_client: Redis, clock: Clock) -> SessionService:
    return SessionService(redis_client, clock)


async def _row(db: AsyncSession, session_id: str) -> UserSession:
    row = await db.scalar(
        select(UserSession)
        .where(UserSession.id_hash == id_hash(session_id))
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def test_create_stores_redis_and_row(
    db_session: AsyncSession, service: SessionService
) -> None:
    await as_app(db_session)
    user = await make_user(db_session, SystemRole.MODERATOR)
    sid, record = await service.create(
        db_session, user.id, [SystemRole.MODERATOR], POLICY, ip="10.0.0.7", user_agent="x" * 600
    )
    assert len(sid) >= 43  # 256 бит в base64url
    loaded = await service.load(sid)
    assert loaded.record == record
    assert loaded.expired is None
    row = await _row(db_session, sid)
    assert row.user_id == user.id
    assert str(row.ip) == "10.0.0.7"
    assert row.user_agent is not None
    assert len(row.user_agent) == 512
    assert row.revoked_at is None
    assert abs(row.expires_at.timestamp() - record.absolute_at) < 1
    # в Redis — только хэш идентификатора
    assert await service._redis.exists(f"session:{id_hash(sid).hex()}") == 1
    assert (await service.load("unknown")).record is None


@pytest.mark.spec("FR-SESS-02")
async def test_idle_timeout_and_background(
    db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    await as_app(db_session)
    user = await make_user(db_session, SystemRole.ADMIN)
    sid, record = await service.create(db_session, user.id, ["admin"], POLICY, ip="10.0.0.1")
    assert record.idle_seconds == 15 * 60
    clock.advance(10 * 60)
    record = await service.touch(db_session, sid, record, background=True)
    clock.advance(6 * 60)  # 16 минут без пользовательских запросов
    loaded = await service.load(sid)
    assert loaded.expired is ExpiryReason.IDLE
    assert (await service.load(sid)).record is None, "истёкшая запись удалена"


@pytest.mark.spec("FR-SESS-02")
async def test_user_activity_extends_and_syncs_db(
    db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    sid, _ = await service.create(db_session, user.id, [], POLICY, ip="10.0.0.1")
    first_seen = (await _row(db_session, sid)).last_seen_at
    for _ in range(3):
        clock.advance(50 * 60)
        loaded = await service.load(sid)
        assert loaded.expired is None
        assert loaded.record is not None
        await service.touch(db_session, sid, loaded.record, background=False)
    assert (await _row(db_session, sid)).last_seen_at > first_seen
    clock.advance(POLICY.absolute_seconds)
    assert (await service.load(sid)).expired is ExpiryReason.ABSOLUTE


async def test_pre_mfa_session_limited(
    db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    sid, _ = await service.create(
        db_session, user.id, [], POLICY, ip="10.0.0.1", enrollment_required=True
    )
    clock.advance(PRE_MFA_SECONDS - 60)
    loaded = await service.load(sid)
    assert loaded.record is not None
    await service.touch(db_session, sid, loaded.record, background=False)
    clock.advance(61)
    assert (await service.load(sid)).expired is ExpiryReason.PRE_MFA_LIMIT


@pytest.mark.spec("FR-SESS-03")
async def test_rotate_supersedes_old_id(db_session: AsyncSession, service: SessionService) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    sid, record = await service.create(db_session, user.id, [], POLICY, ip="10.0.0.1")
    new_sid, new_record = await service.rotate(db_session, sid, record, mfa_passed=True)
    assert new_sid != sid
    assert (await service.load(sid)).record is None
    assert (await service.load(new_sid)).record == new_record
    assert new_record.mfa_passed
    assert new_record.absolute_at == record.absolute_at, "смена id не продлевает абсолютный срок"
    old = await _row(db_session, sid)
    assert old.revoke_reason == "superseded"
    assert old.revoked_at is not None
    assert (await _row(db_session, new_sid)).mfa_passed


@pytest.mark.spec("FR-AUTH-LOC-02")
async def test_session_limit_closes_oldest(
    db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    policy = SessionPolicy(max_sessions=2)
    ids = []
    for _ in range(3):
        sid, _ = await service.create(db_session, user.id, [], policy, ip="10.0.0.1")
        ids.append(sid)
        clock.advance(1)
    assert (await service.load(ids[0])).record is None
    assert (await service.load(ids[1])).record is not None
    assert (await service.load(ids[2])).record is not None
    assert (await _row(db_session, ids[0])).revoke_reason == "superseded"
    audit_row = (
        await db_session.execute(
            text(
                "SELECT details FROM audit.audit_log WHERE event_type = 'auth.sessions.terminated' "
                "AND user_id = :uid"
            ),
            {"uid": user.id},
        )
    ).scalar_one()
    assert audit_row == {"count": 1, "reason": "session_limit", "actor": "system"}


@pytest.mark.spec("FR-SESS-05")
async def test_revoke_user_except_current_and_listener(
    db_session: AsyncSession, service: SessionService
) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    ids = [
        (await service.create(db_session, user.id, [], POLICY, ip="10.0.0.1"))[0] for _ in range(3)
    ]
    ended: list[SessionEnded] = []
    add_session_ended_listener(ended.append)
    try:
        count = await service.revoke_user(
            db_session, user.id, RevokeReason.USER_REVOKED, except_session_id=ids[2]
        )
        assert count == 2
        assert ended == [], "слушатели — только после commit"
        await db_session.commit()
        await run_after_commit(db_session)
    finally:
        remove_session_ended_listener(ended.append)
    assert {e.session_hash for e in ended} == {id_hash(ids[0]), id_hash(ids[1])}
    assert all(e.reason == "user_revoked" for e in ended)
    assert (await service.load(ids[0])).record is None
    assert (await service.load(ids[2])).record is not None
    assert (await _row(db_session, ids[1])).revoke_reason == "user_revoked"
    assert (await _row(db_session, ids[2])).revoked_at is None
    assert await service.active_hashes(user.id) == [id_hash(ids[2])]


async def test_end_and_update(db_session: AsyncSession, service: SessionService) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    sid, record = await service.create(db_session, user.id, [], POLICY, ip="10.0.0.1")
    step_up = record.created_at + 300
    updated = await service.update(db_session, sid, record, step_up_until=step_up)
    loaded: Any = await service.load(sid)
    assert loaded.record.step_up_until == step_up == updated.step_up_until
    assert (await _row(db_session, sid)).step_up_until is not None
    await service.end(db_session, sid, user.id, RevokeReason.LOGOUT)
    assert (await service.load(sid)).record is None
    assert (await _row(db_session, sid)).revoke_reason == "logout"


@pytest.mark.spec("ARCH-05")
async def test_redis_loss_means_relogin(
    db_session: AsyncSession, service: SessionService, redis_client: Redis
) -> None:
    await as_app(db_session)
    user = await make_user(db_session)
    sid, _ = await service.create(db_session, user.id, [], POLICY, ip="10.0.0.1")
    await redis_client.delete(f"session:{id_hash(sid).hex()}")
    loaded = await service.load(sid)
    assert loaded.record is None
    assert loaded.expired is None
