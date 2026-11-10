"""SEC-016: ``estimator audit purge`` (SEC-AUD-04, NFR-REL-06, Q-38).

Отдельная пустая база: purge удаляет записи всего журнала, общая тестовая база для этого не годится.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from typer.testing import CliRunner

from estimator.config import Settings
from estimator.db import roles
from estimator.db.session import create_engine
from estimator.security import audit
from estimator.security.audit import purge
from estimator.security.audit.verify import verify_chain
from tests.integration.db.conftest import alembic, empty_database_url  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-04")]


def _settings(url: str) -> Settings:
    return Settings(database_url=url)


async def _write(engine: AsyncEngine, n: int, mark: str) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    for i in range(n):
        await audit.write_standalone("auth.logout", "success", sessionmaker=maker,
                                     login=f"{mark}{i}", actor="anonymous")  # fmt: skip


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


def test_purge_keeps_chain_verifiable(empty_database_url: str) -> None:  # noqa: F811
    alembic(empty_database_url, "upgrade", "head")
    settings = _settings(empty_database_url)

    async def run() -> None:
        app = create_engine(settings)
        purger = create_engine(settings, role=roles.AUDIT_PURGE)
        try:
            await _write(app, 3, "old")
            cut = (await _rows(app, "SELECT clock_timestamp()"))[0][0]
            await _write(app, 2, "new")
            last_old = (await _rows(app, "SELECT id, hash FROM audit.audit_log "
                                         "WHERE login = 'old2'"))[0]  # fmt: skip

            async with purger.begin() as conn:
                assert await purge.purge_before(conn, cut, dry_run=True) == (3, last_old[1].hex())
            assert len(await _rows(app, "SELECT id FROM audit.audit_log")) == 5

            async with purger.begin() as conn:
                deleted, anchor = await purge.purge_before(conn, cut)
            assert (deleted, anchor) == (3, bytes(last_old[1]).hex())
            left = await _rows(app, "SELECT login FROM audit.audit_log ORDER BY id")
            assert [r[0] for r in left] == ["new0", "new1"]
            stored = await _rows(app, "SELECT last_purged_id, last_purged_hash, purged_until "
                                      "FROM audit.audit_anchor")  # fmt: skip
            assert (stored[0][0], bytes(stored[0][1])) == (last_old[0], bytes(last_old[1]))
            assert stored[0][2] == cut
            async with app.connect() as conn:
                result = await verify_chain(conn)
            assert (result.ok, result.checked) == (True, 2)

            # Второй purge сдвигает якорь; новые записи продолжают цепочку от него
            everything = (await _rows(app, "SELECT clock_timestamp()"))[0][0]
            async with purger.begin() as conn:
                assert (await purge.purge_before(conn, everything))[0] == 2
            await _write(app, 1, "after")
            async with app.connect() as conn:
                assert (await verify_chain(conn)).ok

            async with purger.begin() as conn:
                assert await purge.purge_before(conn, cut) == (0, None)  # нечего удалять

            # У роли purge нет права читать настройки приложения
            with pytest.raises(Exception, match="permission denied"):
                async with purger.begin() as conn:
                    await conn.execute(text("SELECT key FROM system_settings"))
        finally:
            await purger.dispose()
            await app.dispose()

    asyncio.run(run())


def test_run_uses_retention_setting_and_writes_event(empty_database_url: str) -> None:  # noqa: F811
    alembic(empty_database_url, "upgrade", "head")
    settings = _settings(empty_database_url)

    async def run() -> None:
        app = create_engine(settings)
        try:
            await _write(app, 2, "x")
            today = dt.datetime.now(dt.UTC).date()
            dry = await purge.run(settings, today=today, dry_run=True)
            assert (dry.months, dry.deleted, dry.before) == (12, 0, purge.boundary(today, 12))
            assert not await _rows(app, "SELECT id FROM audit.audit_log "
                                        "WHERE event_type = 'system.audit.purged'")  # fmt: skip

            # Срок 6 мес., «сегодня» через 7 мес. — обе записи старше границы
            async with app.begin() as conn:
                await conn.execute(
                    text("INSERT INTO system_settings (key, value) VALUES "
                         "('retention.periods', CAST(:v AS jsonb))"),
                    {"v": json.dumps({"audit_months": 6})},
                )  # fmt: skip
            future = today + dt.timedelta(days=7 * 31)
            done = await purge.run(settings, today=future, os_user="ops")
            assert (done.months, done.deleted) == (6, 2)
            event = await _rows(app, "SELECT details, result::text FROM audit.audit_log "
                                     "WHERE event_type = 'system.audit.purged'")  # fmt: skip
            assert {k: event[0][0][k] for k in done.details()} == done.details()
            assert event[0][0]["before"] == purge.boundary(future, 6).isoformat()
            assert event[0][1] == "success"
            async with app.connect() as conn:
                assert (await verify_chain(conn)).ok, "событие о purge продолжает цепочку от якоря"

            async with app.begin() as conn:
                await conn.execute(
                    text("UPDATE system_settings SET value = CAST(:v AS jsonb) "
                         "WHERE key = 'retention.periods'"),
                    {"v": json.dumps({"audit_months": 3})},
                )  # fmt: skip
            with pytest.raises(purge.PurgeError, match="меньше минимума"):
                await purge.run(settings, today=future)
        finally:
            await app.dispose()

    asyncio.run(run())


def test_cli(empty_database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    alembic(empty_database_url, "upgrade", "head")
    import estimator.cli as cli
    from estimator.config import get_settings

    cli.load_commands()
    cli_app = cli.app

    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    get_settings.cache_clear()
    runner = CliRunner()
    dry = runner.invoke(cli_app, ["audit", "purge", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Ничего не удалено" in dry.output
    done = runner.invoke(cli_app, ["audit", "purge"])
    assert done.exit_code == 0, done.output
    assert "Удалено записей старше" in done.output

    async def events() -> list[str]:
        engine = create_engine(get_settings())
        try:
            rows = await _rows(engine, "SELECT event_type FROM audit.audit_log ORDER BY id")
            return [r[0] for r in rows]
        finally:
            await engine.dispose()

    names = asyncio.run(events())
    assert names == ["system.audit.purged"], "--dry-run событие не пишет"


@pytest.mark.parametrize(
    ("today", "months", "expected"),
    [
        (dt.date(2026, 11, 10), 12, dt.date(2025, 11, 10)),
        (dt.date(2026, 8, 31), 6, dt.date(2026, 2, 28)),
        (dt.date(2028, 8, 31), 6, dt.date(2028, 2, 29)),
        (dt.date(2026, 3, 31), 7, dt.date(2025, 8, 31)),
        (dt.date(2026, 12, 31), 6, dt.date(2026, 6, 30)),
    ],
)
def test_boundary(today: dt.date, months: int, expected: dt.date) -> None:
    assert purge.boundary(today, months) == expected


def test_boundary_minimum() -> None:
    with pytest.raises(purge.PurgeError):
        purge.boundary(dt.date(2026, 11, 10), 5)
