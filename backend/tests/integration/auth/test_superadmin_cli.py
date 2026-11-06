"""AUTH-011: суперадминистратор из консоли (FR-SA-01, FR-2FA-03, Q-22, BR-ROLE-03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import superadmin
from estimator.auth.passwords import activate, reset
from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import SessionService
from estimator.auth.superadmin import SuperadminError
from estimator.auth.tokens import find_valid, token_hash
from estimator.db.enums import AuthTokenKind, SystemRole, UserStatus
from estimator.db.models.users import AuthToken, BackupCode, User
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SA-01")]
BASE = "https://estimator.example"
NEW_PASSWORD = "new horse battery staple 2026"  # nosec B105 — тестовый пароль


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


async def _audit(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"), {"e": event}
    )
    return [r[0] for r in rows.all()]


@pytest.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    await as_app(db_session)
    return db_session


async def test_create_then_reissue_then_activate(db: AsyncSession) -> None:
    issued = await superadmin.create_superadmin(
        db, login="root.one", email="sec@example.com", base_url=BASE, os_user="ops"
    )
    assert issued.link.startswith(f"{BASE}/activate?token=")
    assert issued.expires_minutes == 60
    user = await db.scalar(select(User).where(User.login == "root.one"))
    assert user is not None
    assert user.status is UserStatus.PENDING_PASSWORD
    assert user.password_hash is None
    row = await db.scalar(
        select(AuthToken).where(AuthToken.token_hash == token_hash(_token(issued.link)))
    )
    assert row is not None
    assert row.expires_at - row.created_at == timedelta(minutes=60)
    created = await _audit(db, "users.created")
    assert created[-1] == {"source": "cli", "roles": ["superadmin"], "actor": "cli",
                           "os_user": "ops"}  # fmt: skip

    again = await superadmin.issue_activation(db, login="root.one", base_url=BASE, os_user="ops")
    assert await find_valid(db, _token(issued.link), AuthTokenKind.ACTIVATION) is None
    await activate(db, _token(again.link), NEW_PASSWORD)
    assert user.status is UserStatus.ACTIVE
    with pytest.raises(SuperadminError, match="reset-superadmin"):
        await superadmin.issue_activation(db, login="root.one", base_url=BASE, os_user="ops")


@pytest.mark.spec("BR-ROLE-03")
async def test_refusals(db: AsyncSession) -> None:
    for _ in range(3):
        await make_user(db, SystemRole.SUPERADMIN)
    existing = await make_user(db, SystemRole.SUPERADMIN, status=UserStatus.BLOCKED)
    count = await db.scalar(select(func.count()).select_from(User))
    with pytest.raises(SuperadminError, match="BR-ROLE-03"):
        await superadmin.create_superadmin(db, login="root.four", email="a@b.c", base_url=BASE,
                                           os_user="ops")  # fmt: skip
    assert await db.scalar(select(func.count()).select_from(User)) == count
    with pytest.raises(SuperadminError, match="занят"):
        await superadmin.create_superadmin(db, login=existing.login, email="a@b.c",
                                           base_url=BASE, os_user="ops")  # fmt: skip
    with pytest.raises(SuperadminError, match="Нужны"):
        await superadmin.create_superadmin(db, login=" ", email="a@b.c", base_url=BASE,
                                           os_user="ops")  # fmt: skip
    plain = await make_user(db, SystemRole.ADMIN)
    cases = [("nobody", "не найден"), (plain.login, "не суперадминистратор"),
             (existing.login, "blocked")]  # fmt: skip
    for login, message in cases:
        with pytest.raises(SuperadminError, match=message):
            await superadmin.reset_superadmin(
                db,
                None,
                login=login,
                base_url=BASE,
                os_user="ops",  # type: ignore[arg-type]
            )


@pytest.mark.spec("FR-2FA-03")
@pytest.mark.spec("Q-22")
async def test_reset_superadmin(db: AsyncSession, redis_client: Redis) -> None:
    sessions = SessionService(redis_client)
    user = await make_user(db, SystemRole.SUPERADMIN)
    user.totp_enabled = True
    user.totp_secret_enc = b"x" * 40
    db.add(BackupCode(user_id=user.id, code_hash="h"))
    await sessions.create(db, user.id, [SystemRole.SUPERADMIN], SessionPolicy(), ip="10.0.0.1")
    await db.flush()

    issued = await superadmin.reset_superadmin(
        db, sessions, login=user.login, base_url=BASE, os_user="ops"
    )
    assert issued.link.startswith(f"{BASE}/password/reset?token=")
    assert (user.totp_enabled, user.totp_secret_enc) == (False, None)
    left = await db.scalar(
        select(func.count()).select_from(BackupCode).where(BackupCode.user_id == user.id)
    )
    assert left == 0
    assert await sessions.active_hashes(user.id) == []
    assert (await _audit(db, "auth.password.reset_issued"))[-1]["delivery"] == "cli"
    assert (await _audit(db, "auth.mfa.reset"))[-1]["target_roles"] == ["superadmin"]
    terminated = (await _audit(db, "auth.sessions.terminated"))[-1]
    assert (terminated["count"], terminated["reason"]) == (1, "password_reset")
    row = await db.scalar(
        select(AuthToken).where(AuthToken.token_hash == token_hash(_token(issued.link)))
    )
    assert row is not None
    assert row.expires_at <= datetime.now(UTC) + timedelta(minutes=61)
    await reset(db, sessions, _token(issued.link), NEW_PASSWORD)

    pending = await make_user(db, SystemRole.SUPERADMIN, status=UserStatus.PENDING_PASSWORD,
                              password_hash_value=None)  # fmt: skip
    with pytest.raises(SuperadminError, match="issue-activation"):
        await superadmin.reset_superadmin(db, sessions, login=pending.login, base_url=BASE,
                                          os_user="ops")  # fmt: skip
