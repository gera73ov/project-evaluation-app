"""SEC-004: запись аудита через audit.append, проверка цепочки, оповещения, хук CLI.

SPEC SEC-AUD-01…03, TC-AUD-01 (параллельная нагрузка — QA-010).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from estimator.cli import CommandRun
from estimator.security import audit
from estimator.security.audit.runs import AuditCliHook, verify_and_record
from estimator.security.audit.verify import LAST_RESULT_KEY, verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-03")]


async def _last(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT event_type, result::text, login, host(ip), object_type, object_id, "
                "details, session_hash, user_agent FROM audit.audit_log ORDER BY id DESC LIMIT 1"
            )
        )
    ).one()
    keys = ("type", "result", "login", "ip", "object_type", "object_id", "details",
            "session_hash", "user_agent")  # fmt: skip
    return dict(zip(keys, row, strict=True))


@pytest.mark.spec("SEC-AUD-01")
async def test_write_in_action_transaction(db_session: AsyncSession) -> None:
    await db_session.execute(text("SET LOCAL ROLE estimator_app"))
    audit_id = await audit.write(
        db_session,
        "auth.login.failed",
        "failure",
        login="i.ivanov",
        ip="10.0.0.7",
        user_agent="Firefox",
        session_id="raw-session-id",
        object_type="user",
        details={"reason": "wrong_password", "method": "local", "step": "password"},
        actor="anonymous",
    )
    assert audit_id > 0
    row = await _last(db_session)
    assert row["type"] == "auth.login.failed"
    assert row["result"] == "failure"
    assert row["ip"] == "10.0.0.7"
    assert row["details"]["actor"] == "anonymous"
    assert bytes(row["session_hash"]) == audit.session_hash("raw-session-id")
    assert (await verify_chain(db_session)).ok


async def test_rollback_of_action_rolls_back_audit(db_engine: Any) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    marker = f"rb-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        await audit.write(session, "auth.logout", login=marker)
        await session.rollback()
    async with maker() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM audit.audit_log WHERE login = :l"), {"l": marker}
            )
        ).scalar_one()
    assert count == 0


async def test_verify_detects_modified_and_removed_rows(db_session: AsyncSession) -> None:
    ids = [await audit.write(db_session, "auth.logout", login=f"u{i}") for i in range(4)]
    assert (await verify_chain(db_session)).ok
    # владелец таблицы (тестовая роль) правит запись в обход audit.append
    await db_session.execute(
        text("UPDATE audit.audit_log SET login = 'evil' WHERE id = :i"), {"i": ids[1]}
    )
    broken = await verify_chain(db_session)
    assert (broken.ok, broken.first_broken_id, broken.reason) == (False, str(ids[1]), "modified")
    await db_session.execute(
        text("UPDATE audit.audit_log SET login = 'u1' WHERE id = :i"), {"i": ids[1]}
    )
    assert (await verify_chain(db_session)).ok
    await db_session.execute(text("DELETE FROM audit.audit_log WHERE id = :i"), {"i": ids[2]})
    gap = await verify_chain(db_session, batch=2)
    assert (gap.ok, gap.first_broken_id, gap.reason) == (False, str(ids[3]), "chain")


@pytest.mark.spec("SEC-AUTH-07")
async def test_alert_listener_runs_after_commit_only(db_engine: Any) -> None:
    from estimator.db.session import transaction

    seen: list[audit.Alert] = []
    audit.add_alert_listener(seen.append)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    try:

        async def failing_action() -> None:
            async with transaction(maker) as session:
                await audit.write(
                    session, "security.login_failures_burst", object_type="user",
                    details={"failures_hour": 21, "distinct_ips": 3},
                )  # fmt: skip
                raise RuntimeError("действие упало")

        with pytest.raises(RuntimeError):
            await failing_action()
        assert seen == []
        async with transaction(maker) as session:
            await audit.write(
                session, "security.login_failures_burst", login="victim", object_type="user",
                details={"failures_hour": 21, "distinct_ips": 3},
            )  # fmt: skip
            await audit.write(session, "auth.logout")  # без оповещения
        assert [a.event_type for a in seen] == ["security.login_failures_burst"]
        assert seen[0].login == "victim"
    finally:
        audit.remove_alert_listener(seen.append)


async def test_write_validates(db_session: AsyncSession) -> None:
    with pytest.raises(audit.AuditError):
        await audit.write(db_session, "auth.logout", "maybe")
    with pytest.raises(audit.AuditError):
        await audit.write(db_session, "auth.logout", object_type="planet")


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, test_database_url: str) -> str:
    from estimator.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    get_settings.cache_clear()
    return test_database_url


async def _count(url: str, sql: str, **params: Any) -> Any:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()
    finally:
        await engine.dispose()


async def test_verify_and_record(app_env: str, redis_client: Any) -> None:
    result = await verify_and_record(actor="cli", os_user="ops")
    assert result.ok
    last = await _count(
        app_env,
        "SELECT details FROM audit.audit_log WHERE event_type = 'system.audit_chain.verified' "
        "ORDER BY id DESC LIMIT 1",
    )
    assert last["ok"] is True
    assert last["actor"] == "cli"
    assert last["os_user"] == "ops"
    stored = json.loads(await redis_client.get(LAST_RESULT_KEY))
    assert stored["ok"] is True


def test_cli_hook_writes_audited_commands_only(app_env: str) -> None:
    import asyncio

    marker = f"sa-{uuid.uuid4().hex[:8]}"
    hook = AuditCliHook()
    run = CommandRun(
        name="issue-activation",
        os_user="ops",
        app_env="test",
        argument_names=["login", "password_file"],
        public_args={"login": marker},
    )
    hook.after(run, "ok", None)
    hook.after(CommandRun("config-env", "ops", "test", []), "ok", None)
    details = asyncio.run(
        _count(
            app_env,
            "SELECT details FROM audit.audit_log WHERE event_type = 'system.cli.executed' "
            "AND details->'args'->>'login' = :m",
            m=marker,
        )
    )
    assert details["command"] == "issue-activation"
    # имя аргумента секретное — значение маскируется
    assert details["args"] == {"login": marker, "password_file": "***"}
    assert details["os_user"] == "ops"
    assert details["actor"] == "cli"
    assert details["exit_code"] == 0
    count = asyncio.run(
        _count(app_env, "SELECT count(*) FROM audit.audit_log "
                        "WHERE details->>'command' = 'config-env'")
    )  # fmt: skip
    assert count == 0


def test_cli_hook_never_breaks_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from estimator.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@127.0.0.1:1/none")
    get_settings.cache_clear()
    AuditCliHook().after(CommandRun("migrate", "ops", "test", []), "error", RuntimeError())
