"""QA-001 · изолированная тестовая БД PostgreSQL (SPEC 13.1, NFR-MNT-01).

* ``TEST_DATABASE_URL`` — адрес сервера PostgreSQL 16 (драйвер asyncpg) с правом
  ``CREATEDB``, например ``postgresql+asyncpg://estimator:…@127.0.0.1:5432/postgres``. Без
  переменной тесты с фикстурами БД пропускаются, остальные идут как обычно.
* Каждый процесс pytest-xdist получает свою базу ``estimator_test_<воркер>``: она создаётся
  заново в начале прогона и удаляется в конце (:func:`test_database_url`).
* Каждый тест работает в транзакции, которая откатывается после теста (:func:`db_session`).
  ``session.commit()`` внутри теста фиксирует только точку сохранения (SAVEPOINT), поэтому
  тесты не видят данных друг друга и могут идти параллельно.

Схему создаёт :func:`prepare_schema`: когда появится Alembic (DB-002) — ``alembic upgrade head``.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ENV_VAR = "TEST_DATABASE_URL"
BACKEND = Path(__file__).resolve().parents[2]
_SAFE_NAME = re.compile(r"[a-z0-9_]{1,63}")


def database_name(worker: str) -> str:
    """Имя базы процесса: ``estimator_test_gw0`` под xdist, ``estimator_test_main`` без него."""
    name = f"estimator_test_{worker}".lower()
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"недопустимое имя тестовой базы: {name}")
    return name


async def recreate_database(server_url: str, name: str, *, drop_only: bool = False) -> None:
    """Пересоздать (или удалить) базу ``name`` на сервере из ``server_url``."""
    engine = create_async_engine(server_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            # имя проверено _SAFE_NAME; идентификатор нельзя передать параметром запроса
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            if not drop_only:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


#: INF-015: каталог backend другой версии, чьи миграции накатываются вместо своих — проверка CI
#: «старый код на новой схеме» (тесты прежней версии на схеме из PR).
ALEMBIC_DIR_ENV = "TEST_ALEMBIC_DIR"


def prepare_schema(url: str) -> None:
    """Накатить схему на пустую базу. До DB-002 (Alembic) схемы нет — ничего не делает."""
    source = Path(os.environ.get(ALEMBIC_DIR_ENV) or BACKEND)
    if not (source / "alembic.ini").is_file():
        return
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=source,
        env={**os.environ, "DATABASE_URL": url}
        | ({"PYTHONPATH": str(source / "src")} if source != BACKEND else {}),
        check=True,
    )


@asynccontextmanager
async def isolated_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия внутри внешней транзакции, которая всегда откатывается."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


def worker_name(config: pytest.Config) -> str:
    """ID воркера pytest-xdist (gw0, gw1…) или ``main`` без xdist."""
    workerinput = getattr(config, "workerinput", None)
    return workerinput["workerid"] if workerinput else "main"


@pytest.fixture(scope="session")
def test_database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """Адрес отдельной базы этого процесса pytest (создаётся на время прогона)."""
    server_url = os.environ.get(ENV_VAR)
    if not server_url:
        pytest.skip(f"{ENV_VAR} не задан: тесты с БД пропущены")
    name = database_name(worker_name(request.config))
    asyncio.run(recreate_database(server_url, name))
    url = make_url(server_url).set(database=name).render_as_string(hide_password=False)
    prepare_schema(url)
    yield url
    asyncio.run(recreate_database(server_url, name, drop_only=True))


@pytest.fixture
async def db_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Движок тестовой базы. NullPool: соединение не переживает цикл событий теста."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия SQLAlchemy теста: всё, что тест записал, откатывается после него."""
    async with isolated_session(db_engine) as session:
        yield session
