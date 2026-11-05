"""DB-011 на живой БД: роль соединения, UTC, хуки только после настоящего commit."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from estimator.config import Settings
from estimator.db import session as db
from estimator.db.models.users import User
from estimator.db.uuid7 import uuid7

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-REL-04")]


@pytest.fixture
async def maker(test_database_url: str):
    engine = db.create_engine(Settings(database_url=test_database_url))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_connection_runs_as_app_role_in_utc(maker) -> None:
    async with db.transaction(maker) as session:
        assert await session.scalar(text("SELECT current_user")) == "estimator_app"
        assert await session.scalar(text("SHOW timezone")) == "UTC"


async def test_hook_sees_committed_data_and_rollback_skips_it(maker) -> None:
    login = f"hook.{uuid7().hex[:8]}"
    seen: list[int] = []

    async def check() -> None:
        async with maker() as other:
            seen.append(
                await other.scalar(
                    select(func.count()).select_from(User).where(User.login == login)
                )
            )

    with pytest.raises(RuntimeError):  # noqa: PT012 — откат блока проверяется целиком
        async with db.transaction(maker) as session:
            session.add(User(login=login, full_name="Откат"))
            db.after_commit(session, check)
            await session.flush()
            raise RuntimeError("откат")
    assert seen == []

    async with db.transaction(maker) as session:
        session.add(User(login=login, full_name="Фиксация"))
        db.after_commit(session, check)
    assert seen == [1], "хук выполняется после commit: другая сессия уже видит строку"
