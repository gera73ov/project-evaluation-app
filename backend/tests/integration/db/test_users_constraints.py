"""DB-003: ограничения таблиц пользователей, ролей, сессий, токенов и настроек."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.settings import SystemSetting
from estimator.db.models.users import (
    ANONYMIZED_NO_SEQ,
    AuthToken,
    User,
    UserRole,
    UserSession,
)
from estimator.db.uuid7 import uuid7
from tests.integration.db.conftest import as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.2")]


def _user(login: str, **kw: object) -> User:
    fields: dict[str, object] = {"full_name": f"Тест {login}", "status": UserStatus.ACTIVE}
    return User(login=login, **{**fields, **kw})


async def _rejects(session: AsyncSession, obj: object) -> None:
    with pytest.raises(IntegrityError):  # noqa: PT012 — откат блока проверяется целиком
        async with session.begin_nested():
            session.add(obj)
            await session.flush()


async def test_login_unique_case_insensitive(db_session: AsyncSession) -> None:
    db_session.add(_user("I.Ivanov"))
    await db_session.flush()
    await _rejects(db_session, _user("i.ivanov"))


async def test_email_unique_only_when_set(db_session: AsyncSession) -> None:
    db_session.add_all([_user("user1", email="A@x.test"), _user("user2"), _user("user3")])
    await db_session.flush()
    await _rejects(db_session, _user("user4", email="a@X.test"))


@pytest.mark.spec("FR-AUTH-AD-07")
async def test_ad_group_role_only_for_moderator_and_presale(db_session: AsyncSession) -> None:
    user = _user("ad.user", source=UserSource.AD, ad_object_guid=uuid.uuid4())
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role=SystemRole.MODERATOR, source=RoleSource.AD_GROUP))
    await db_session.flush()
    await _rejects(
        db_session, UserRole(user_id=user.id, role=SystemRole.ADMIN, source=RoleSource.AD_GROUP)
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": UserStatus.BLOCKED},  # блокировка без причины
        {"block_reason": UserBlockReason.MANUAL},  # причина без блокировки
        {"source": UserSource.AD, "password_hash": "x"},  # пароль у учётки AD
        {"ad_object_guid": uuid.UUID(int=1)},  # GUID у локальной учётки
        {"totp_enabled": True},  # TOTP без секрета
        {"status": UserStatus.ANONYMIZED},  # анонимизация без номера
    ],
    ids=["blocked-no-reason", "reason-not-blocked", "ad-password", "local-guid", "totp", "anon"],
)
async def test_user_row_checks(db_session: AsyncSession, kwargs: dict) -> None:
    await _rejects(db_session, _user("bad.user", **kwargs))


async def test_login_length(db_session: AsyncSession) -> None:
    await _rejects(db_session, _user("ab"))


async def test_anonymized_number_from_sequence(db_session: AsyncSession) -> None:
    number = await db_session.scalar(select(ANONYMIZED_NO_SEQ.next_value()))
    db_session.add(_user("gone", status=UserStatus.ANONYMIZED, anonymized_no=number))
    await db_session.flush()


async def test_session_row(db_session: AsyncSession) -> None:
    user = _user("s.user")
    db_session.add(user)
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add(
        UserSession(
            id_hash=hashlib.sha256(b"sid").digest(),
            user_id=user.id,
            last_seen_at=now,
            expires_at=now + timedelta(hours=12),
            ip="10.0.0.1",
        )
    )
    await db_session.flush()
    token = hashlib.sha256(b"token").digest()
    db_session.add(AuthToken(user_id=user.id, kind="activation", token_hash=token, expires_at=now))
    await db_session.flush()
    await _rejects(
        db_session,
        AuthToken(user_id=user.id, kind="password_reset", token_hash=token, expires_at=now),
    )


async def test_setting_key_format(db_session: AsyncSession) -> None:
    db_session.add(SystemSetting(key="security.password_policy", value={"min_length": 12}))
    await db_session.flush()
    await _rejects(db_session, SystemSetting(key="NoDots", value=1))


async def test_app_role_can_write_users(db_session: AsyncSession) -> None:
    """Права по умолчанию: estimator_app пишет в таблицы public."""
    await as_app(db_session)
    await db_session.execute(
        insert(User).values(id=uuid7(), login="app.user", full_name="Через роль приложения")
    )
    assert await db_session.scalar(text("SELECT current_user")) == "estimator_app"


async def test_app_role_cannot_ddl(db_session: AsyncSession) -> None:
    await as_app(db_session)
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text("CREATE TABLE public.hack (id int)"))
