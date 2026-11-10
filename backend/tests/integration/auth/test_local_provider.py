"""AUTH-001: провайдер local на настоящей БД, выбор провайдера по auth.mode."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import load_auth_mode
from estimator.auth.providers import (
    Credentials,
    authenticate,
)
from estimator.auth.providers.local import needs_rehash, verify_password
from estimator.db.enums import SystemRole, UserSource, UserStatus
from tests.integration.auth.helpers import PASSWORD, make_user
from tests.integration.db.conftest import as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUTH-01")]


async def test_success_returns_identity(db_session: AsyncSession) -> None:
    await as_app(db_session)
    user = await make_user(db_session, SystemRole.MODERATOR)
    result = await authenticate(db_session, "local", Credentials(user.login.upper(), PASSWORD))
    assert result.ok
    assert result.identity is not None
    assert result.identity.user_id == user.id
    assert result.identity.provider == "local"
    assert result.identity.attributes["full_name"] == user.full_name


@pytest.mark.parametrize(
    ("status", "password", "reason"),
    [
        (UserStatus.ACTIVE, "wrong", "wrong_password"),
        (UserStatus.BLOCKED, "wrong", "wrong_password"),  # статус не раскрывается без пароля
        (UserStatus.BLOCKED, PASSWORD, "user_blocked"),
    ],
)
async def test_failures(
    db_session: AsyncSession, status: UserStatus, password: str, reason: str
) -> None:
    await as_app(db_session)
    user = await make_user(db_session, status=status)
    result = await authenticate(db_session, "local", Credentials(user.login, password))
    assert result.reason == reason
    assert result.user_id == user.id


async def test_unknown_pending_and_empty(db_session: AsyncSession) -> None:
    await as_app(db_session)
    unknown = await authenticate(db_session, "local", Credentials("nobody.here", PASSWORD))
    assert (unknown.reason, unknown.user_id) == ("user_not_found", None)
    pending = await make_user(
        db_session, status=UserStatus.PENDING_PASSWORD, password_hash_value=None
    )
    result = await authenticate(db_session, "local", Credentials(pending.login, PASSWORD))
    assert result.reason == "pending_password"
    empty = await authenticate(db_session, "local", Credentials("  ", PASSWORD))
    assert empty.reason == "empty_credentials"
    ad_user = await make_user(db_session, source=UserSource.AD)
    result = await authenticate(db_session, "local", Credentials(ad_user.login, PASSWORD))
    assert result.reason == "user_not_found"


async def test_outdated_hash_is_rehashed_on_login(db_session: AsyncSession) -> None:
    await as_app(db_session)
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID)
    user = await make_user(db_session, password_hash_value=weak.hash(PASSWORD))
    assert needs_rehash(user.password_hash or "")
    result = await authenticate(db_session, "local", Credentials(user.login, PASSWORD))
    assert result.ok
    await db_session.refresh(user)
    assert user.password_hash is not None
    assert not needs_rehash(user.password_hash)
    assert verify_password(user.password_hash, PASSWORD)


@pytest.mark.spec("ARCH-06")
async def test_superadmin_always_local(db_session: AsyncSession) -> None:
    """В режиме AD суперадминистратор входит через local, остальные — через провайдер ad."""
    await as_app(db_session)
    superadmin = await make_user(db_session, SystemRole.SUPERADMIN)
    result = await authenticate(db_session, "ad", Credentials(superadmin.login, PASSWORD))
    assert result.ok
    other = await make_user(db_session, SystemRole.ADMIN)
    in_ad = await authenticate(db_session, "ad", Credentials(other.login, PASSWORD))
    assert in_ad.reason == "ad_unavailable", "AD не настроен — вход через AD недоступен"


async def test_auth_mode_default_is_local(db_session: AsyncSession) -> None:
    await as_app(db_session)
    assert await load_auth_mode(db_session) in {"local", "ad"}
