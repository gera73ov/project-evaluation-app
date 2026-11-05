"""Общие фикстуры интеграционных тестов трека DB (нужен ``TEST_DATABASE_URL``)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from tests.plugins.database import BACKEND, ENV_VAR, database_name, recreate_database, worker_name

pytestmark = pytest.mark.integration


def alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Запустить Alembic из каталога backend против базы ``url``."""
    return subprocess.run(  # noqa: S603 — фиксированная команда alembic
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def empty_database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """Отдельная пустая база для тестов миграций (удаляется после теста)."""
    server_url = os.environ.get(ENV_VAR)
    if not server_url:
        pytest.skip(f"{ENV_VAR} не задан: тесты с БД пропущены")
    name = database_name(f"{worker_name(request.config)}_mig")
    asyncio.run(recreate_database(server_url, name))
    yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    asyncio.run(recreate_database(server_url, name, drop_only=True))


async def as_app(session: AsyncSession) -> None:
    """Переключить транзакцию теста на роль приложения ``estimator_app``."""
    await session.execute(text("SET LOCAL ROLE estimator_app"))
