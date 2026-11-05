"""DB-009: журнал аудита — только INSERT через функцию, хэш-цепочка, параллельная запись.

SPEC SEC-AUD-02…04, TC-AUD-01 (полная проверка сервиса — QA-010), чек-лист 17.3 CL-12.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
from datetime import UTC
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from estimator.db.models.audit import AuditLog
from tests.integration.db.conftest import alembic, as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-03")]

APPEND = text(
    "SELECT (r).id, (r).hash, (r).prev_hash FROM ("
    "SELECT audit.append(:event_type, CAST(:result AS audit.audit_result), "
    "p_login => :login, p_ip => CAST(:ip AS inet), p_details => CAST(:details AS jsonb)) AS r) s"
)


async def append(
    session: AsyncSession,
    event_type: str = "auth.login.success",
    *,
    result: str = "success",
    login: str | None = "i.ivanov",
    ip: str | None = "10.0.0.7",
    details: dict[str, Any] | None = None,
) -> tuple[int, bytes, bytes]:
    row = (
        await session.execute(
            APPEND,
            {
                "event_type": event_type,
                "result": result,
                "login": login,
                "ip": ip,
                "details": json.dumps(details or {}),
            },
        )
    ).one()
    return row[0], bytes(row[1]), bytes(row[2])


def reference_hash(row: AuditLog) -> bytes:
    """Независимая реализация SEC-AUD-03 на Python (RFC 8785 для данных журнала)."""
    record = {
        "time": row.ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "type": row.event_type,
        "result": row.result.value,
        "user_id": str(row.user_id) if row.user_id else None,
        "login": row.login,
        "ip": str(row.ip) if row.ip is not None else None,
        "user_agent": row.user_agent,
        "session_hash": row.session_hash.hex() if row.session_hash else None,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "details": row.details,
        "prev_hash": row.prev_hash.hex(),
    }
    canonical = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(row.prev_hash + canonical.encode("utf-8")).digest()


async def test_append_builds_chain(db_session: AsyncSession) -> None:
    await as_app(db_session)
    first = await append(db_session)
    second = await append(db_session, "auth.logout", ip="2001:db8::1")
    assert second[2] == first[1], "prev_hash второй записи — hash первой"
    assert second[0] > first[0]


async def test_hash_matches_reference_implementation(db_session: AsyncSession) -> None:
    await as_app(db_session)
    details = {
        "z": [1, "два", {"b": True, "a": None}],
        "a": 'кавычка " и \\ и \n\t\x01',
        "n": 1.5,
        "actor": "user",
    }
    ids = [
        (await append(db_session, details=details))[0],
        (await append(db_session, ip="2001:db8:0:0::1", login=None))[0],
        (await append(db_session, ip=None, result="denied"))[0],
    ]
    rows = (await db_session.scalars(select(AuditLog).where(AuditLog.id.in_(ids)))).all()
    assert len(rows) == 3
    for row in rows:
        assert row.hash == reference_hash(row)
        db_hash = await db_session.scalar(
            text("SELECT audit.row_hash(l) FROM audit.audit_log l WHERE id = :id"), {"id": row.id}
        )
        assert bytes(db_hash) == row.hash


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit.audit_log SET login = 'x'",
        "DELETE FROM audit.audit_log",
        "TRUNCATE audit.audit_log",
        "INSERT INTO audit.audit_log (ts, event_type, result, prev_hash, hash) "
        "VALUES (now(), 'x', 'success', '\\x00', '\\x00')",
        "UPDATE audit.audit_anchor SET purged_at = now()",
        "CREATE TABLE audit.hack (id int)",
    ],
    ids=["update", "delete", "truncate", "insert", "anchor", "create"],
)
@pytest.mark.spec("SEC-AUD-04")
async def test_app_role_cannot_modify_audit(db_session: AsyncSession, statement: str) -> None:
    """CL-12: UPDATE/DELETE/TRUNCATE и прямой INSERT ролью приложения — ошибка прав."""
    await as_app(db_session)
    await append(db_session)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_append_requires_read_committed(db_engine) -> None:
    async with db_engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        with pytest.raises(DBAPIError, match="READ COMMITTED"):
            await conn.execute(
                APPEND,
                {
                    "event_type": "x",
                    "result": "success",
                    "login": None,
                    "ip": None,
                    "details": "{}",
                },
            )
        await conn.rollback()


async def test_ensure_partitions_is_idempotent(db_session: AsyncSession) -> None:
    await as_app(db_session)
    assert await db_session.scalar(text("SELECT audit.ensure_partitions(3)")) == 0
    created = await db_session.scalar(text("SELECT audit.ensure_partitions(6)"))
    assert created == 3
    with pytest.raises(DBAPIError, match="вне диапазона"):
        async with db_session.begin_nested():
            await db_session.execute(text("SELECT audit.ensure_partitions(99)"))


@pytest.mark.tc("TC-AUD-01")
async def test_parallel_transactions_do_not_fork_chain(test_database_url: str) -> None:
    """Две транзакции пишут одновременно: вторая ждёт блокировку и продолжает цепочку первой."""
    engine = create_async_engine(
        test_database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"role": "estimator_app"}},
    )
    first_written = asyncio.Event()
    release_first = asyncio.Event()

    async def first() -> tuple[int, bytes, bytes]:
        async with engine.begin() as conn:
            row = await append(conn)  # type: ignore[arg-type]
            first_written.set()
            await release_first.wait()
            return row

    async def second() -> tuple[int, bytes, bytes]:
        await first_written.wait()
        async with engine.begin() as conn:
            return await append(conn)  # type: ignore[arg-type]

    try:
        task1 = asyncio.create_task(first())
        task2 = asyncio.create_task(second())
        await first_written.wait()
        await asyncio.sleep(0.3)
        assert not task2.done(), "вторая транзакция должна ждать advisory lock"
        release_first.set()
        r1, r2 = await asyncio.gather(task1, task2)
        assert r2[2] == r1[1]
        assert r1[2] != r2[2]

        # Много параллельных записей: все prev_hash различны, цепочка непрерывна
        async def one(i: int) -> None:
            async with engine.begin() as conn:
                await append(conn, details={"i": i})  # type: ignore[arg-type]

        await asyncio.gather(*(one(i) for i in range(20)))
        async with engine.connect() as conn:
            rows = (
                await conn.execute(select(AuditLog.prev_hash, AuditLog.hash).order_by(AuditLog.id))
            ).all()
        assert len({r.prev_hash for r in rows}) == len(rows)
        for prev, cur in itertools.pairwise(rows):
            assert cur.prev_hash == prev.hash
    finally:
        await engine.dispose()
        cleanup = create_async_engine(test_database_url, poolclass=NullPool)
        async with cleanup.begin() as conn:
            await conn.execute(text("TRUNCATE audit.audit_log"))
        await cleanup.dispose()


def test_first_record_uses_zero_hash_then_anchor(empty_database_url: str) -> None:
    alembic(empty_database_url, "upgrade", "head")

    async def run() -> tuple[bytes, bytes]:
        engine = create_async_engine(empty_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                first = await append(conn)  # type: ignore[arg-type]
                await conn.execute(text("SET LOCAL ROLE estimator_audit_purge"))
                await conn.execute(text("DELETE FROM audit.audit_log"))
                await conn.execute(
                    text("INSERT INTO audit.audit_anchor VALUES (1, :id, :hash, now(), now())"),
                    {"id": first[0], "hash": first[1]},
                )
                assert await conn.scalar(select(func.count()).select_from(AuditLog)) == 0
                await conn.execute(text("SET LOCAL ROLE estimator_app"))
                after_purge = await append(conn)  # type: ignore[arg-type]
            return first[2], after_purge[2]
        finally:
            await engine.dispose()

    first_prev, after_purge_prev = asyncio.run(run())
    assert first_prev == bytes(32)
    assert after_purge_prev != bytes(32)


async def test_lock_key_matches_model_constant(db_session: AsyncSession) -> None:
    """Сервис аудита (SEC-004) берёт тот же ключ блокировки, что и ``audit.append``."""
    from estimator.db.models.audit import AUDIT_LOCK_KEY

    body = await db_session.scalar(text("SELECT pg_get_functiondef('audit.append'::regproc)"))
    assert f"pg_advisory_xact_lock({AUDIT_LOCK_KEY})" in body


async def test_periodic_task_creates_partitions(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from estimator.config import get_settings
    from estimator.db import tasks
    from estimator.jobs.celery_app import make_celery

    assert "db.ensure_audit_partitions" in make_celery().conf.beat_schedule
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    assert await tasks.ensure_audit_partitions_async(1) == 0  # миграция уже создала 3 вперёд
