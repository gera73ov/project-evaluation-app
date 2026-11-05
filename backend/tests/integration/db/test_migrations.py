"""DB-002: миграции вверх и вниз на чистой БД, роли, владельцы схем, совпадение с моделями."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from estimator.db import roles
from tests.integration.db.conftest import alembic

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-MNT-02")]


def _query(url: str, sql: str) -> list[tuple]:
    async def run() -> list[tuple]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return [tuple(r) for r in (await conn.execute(text(sql))).all()]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_upgrade_downgrade_upgrade(empty_database_url: str) -> None:
    url = empty_database_url
    alembic(url, "upgrade", "head")
    tables = {
        r[0] for r in _query(url, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
    }
    assert {"users", "user_roles", "sessions", "system_settings", "auth_tokens"} <= tables

    alembic(url, "downgrade", "base")
    left = _query(
        url,
        "SELECT schemaname, tablename FROM pg_tables "
        "WHERE schemaname IN ('public', 'audit') AND tablename <> 'alembic_version'",
    )
    assert left == []
    assert _query(url, "SELECT 1 FROM pg_namespace WHERE nspname = 'audit'") == []
    assert _query(url, "SELECT 1 FROM pg_type WHERE typname = 'user_status'") == []

    alembic(url, "upgrade", "head")
    assert alembic(url, "current").stdout.strip().endswith("(head)")


def test_roles_and_owners(empty_database_url: str) -> None:
    url = empty_database_url
    alembic(url, "upgrade", "head")
    existing = {r[0] for r in _query(url, "SELECT rolname FROM pg_roles")}
    assert set(roles.ALL) <= existing
    # SEC-AUD-03: роль приложения не владеет схемой audit и не может в ней создавать объекты
    owner = _query(url, "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname='audit'")
    assert owner == [(roles.MIGRATOR,)]
    can_create = _query(url, "SELECT has_schema_privilege('estimator_app', 'audit', 'CREATE')")
    assert can_create == [(False,)]
    can_create_public = _query(
        url, "SELECT has_schema_privilege('estimator_app', 'public', 'CREATE')"
    )
    assert can_create_public == [(False,)]
    # Все объекты приложения принадлежат migrator
    foreign = _query(
        url,
        "SELECT c.relname, c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname IN ('public', 'audit') "
        "AND c.relname NOT IN ('alembic_version', 'alembic_version_pkc') "
        "AND c.relowner::regrole::text <> 'estimator_migrator'",
    )
    assert foreign == []


def test_models_match_migrations(empty_database_url: str) -> None:
    """ORM-модели и схема после миграций совпадают (``alembic check`` без расхождений)."""
    alembic(empty_database_url, "upgrade", "head")
    result = alembic(empty_database_url, "check")
    assert "No new upgrade operations detected" in result.stdout + result.stderr
