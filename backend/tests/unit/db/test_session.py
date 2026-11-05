"""DB-011: параметры соединения, хуки after-commit, commit до ответа клиенту (без БД).

Сессия, которая ничего не выполнила, не берёт соединение, поэтому commit и rollback здесь
проходят без PostgreSQL. Проверка на живой БД — tests/integration/db/test_session_db.py.
"""

from __future__ import annotations

import ssl

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimator.config import Settings
from estimator.db import session as db

pytestmark = pytest.mark.spec("NFR-REL-04")

URL = "postgresql+asyncpg://nobody@127.0.0.1:1/none"


@pytest.fixture
def maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_async_engine(URL), expire_on_commit=False)


@pytest.mark.spec("SEC-WEB-05")
def test_connect_args_tls_and_role(tmp_path) -> None:
    plain = db.connect_args(Settings())
    assert plain["ssl"] is False
    assert plain["server_settings"]["timezone"] == "UTC"
    assert "role" not in plain["server_settings"]

    ctx = db.connect_args(Settings(database_sslmode="verify-full"), role="estimator_app")
    assert isinstance(ctx["ssl"], ssl.SSLContext)
    assert ctx["ssl"].check_hostname is True
    assert ctx["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert ctx["server_settings"]["role"] == "estimator_app"

    with pytest.raises(ValueError, match="неизвестная роль"):
        db.connect_args(Settings(), role="postgres")


def test_unknown_sslmode_rejected() -> None:
    with pytest.raises(ValueError, match="database_sslmode"):
        Settings(database_sslmode="prefer")


async def test_hooks_run_after_commit_in_order(maker) -> None:
    calls: list[str] = []

    async def async_hook() -> None:
        calls.append("async")

    async with db.transaction(maker) as session:
        db.after_commit(session, lambda: calls.append("sync"))
        db.after_commit(session, async_hook)
        assert calls == []
    assert calls == ["sync", "async"]


async def test_hooks_dropped_on_rollback(maker) -> None:
    calls: list[str] = []
    with pytest.raises(RuntimeError):  # noqa: PT012 — откат блока проверяется целиком
        async with db.transaction(maker) as session:
            db.after_commit(session, lambda: calls.append("x"))
            raise RuntimeError("сбой")
    assert calls == []


async def test_hook_of_intermediate_commit_runs_at_the_end(maker) -> None:
    calls: list[str] = []
    async with db.transaction(maker) as session:
        db.after_commit(session.sync_session, lambda: calls.append("first"))
        await session.commit()  # промежуточный commit: хук готов, выполнится в конце
        assert calls == []
    assert calls == ["first"]


def _app(maker, events: list[str], fail_commit: bool = False) -> FastAPI:
    async def session_dep():
        async with db.transaction(maker) as session:
            if fail_commit:
                orig = session.commit

                async def broken() -> None:
                    await orig()
                    raise RuntimeError("commit failed")

                session.commit = broken  # type: ignore[method-assign]
            yield session

    app = FastAPI()
    app.dependency_overrides[db.db_session] = session_dep

    @app.post("/thing")
    async def thing(session: db.DbSession) -> dict[str, str]:
        db.after_commit(session, lambda: events.append("commit"))
        return {"ok": "yes"}

    @app.middleware("http")
    async def mark_response(request, call_next):
        response = await call_next(request)
        events.append("response")
        return response

    return app


@pytest.mark.spec("13.1")
def test_commit_happens_before_response(maker) -> None:
    events: list[str] = []
    client = TestClient(_app(maker, events))
    assert client.post("/thing").status_code == 200
    assert events == ["commit", "response"]


def test_failed_commit_is_not_reported_as_success(maker) -> None:
    events: list[str] = []
    client = TestClient(_app(maker, events, fail_commit=True), raise_server_exceptions=False)
    assert client.post("/thing").status_code == 500
    assert "commit" not in events


async def test_engine_cache_and_dispose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    await db.dispose_engine()
    engine = db.get_engine()
    assert db.get_engine() is engine
    assert db.get_sessionmaker().kw["expire_on_commit"] is False
    await db.dispose_engine()
    assert db.get_engine.cache_info().currsize == 0
