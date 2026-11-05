"""DB-011 · асинхронная сессия SQLAlchemy, транзакция на запрос и хуки after-commit.

SPEC 13.1, NFR-REL-04, SEC-WEB-05.

* :func:`connect_args` — параметры asyncpg: роль соединения (``SET ROLE`` стартовым параметром
  ``role``), часовой пояс ``UTC`` (contracts/db/schema.md G-3) и TLS ``verify-full`` по настройке
  ``DATABASE_SSLMODE``.
* :func:`get_engine` / :func:`get_sessionmaker` — один пул на процесс, соединения работают
  от роли ``estimator_app``.
* :func:`transaction` — единица работы: commit при успехе, rollback при исключении, после
  успешного commit выполняются хуки :func:`after_commit` (публикация событий RT-002).
* :func:`db_session` — зависимость FastAPI. Подключается с ``scope="function"``
  (:data:`DbSession`): выход из зависимости, то есть commit, выполняется до отправки ответа,
  поэтому клиент не увидит «успех», который потом откатится.
"""

from __future__ import annotations

import inspect
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from estimator.config import DbSslMode, Settings, get_settings
from estimator.db import roles

#: Хук после commit: обычная функция или корутина без аргументов.
AfterCommit = Callable[[], Awaitable[None] | None]

_PENDING = "estimator.after_commit.pending"
_READY = "estimator.after_commit.ready"


def ssl_context(settings: Settings) -> ssl.SSLContext | bool:
    """TLS-контекст для asyncpg: ``False`` при ``disable``, проверка цепочки и имени при
    ``verify-full``."""
    if settings.database_sslmode is DbSslMode.DISABLE:
        return False
    ctx = ssl.create_default_context(cafile=settings.database_sslrootcert or None)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def connect_args(settings: Settings, role: str | None = None) -> dict[str, Any]:
    """``connect_args`` движка: TLS, UTC и (если задана) роль соединения."""
    server_settings = {"timezone": "UTC", "application_name": "estimator"}
    if role is not None:
        if role not in roles.ALL:
            raise ValueError(f"неизвестная роль БД: {role}")
        server_settings["role"] = role
    return {"ssl": ssl_context(settings), "server_settings": server_settings}


def create_engine(settings: Settings, role: str = roles.APP, **kwargs: Any) -> AsyncEngine:
    """Движок с пулом; все соединения — от роли ``role``."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        connect_args=connect_args(settings, role),
        pool_pre_ping=True,
        **kwargs,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    """Движок процесса (роль ``estimator_app``)."""
    return create_engine(get_settings())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def dispose_engine() -> None:
    """Закрыть пул (остановка процесса, тесты)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


# --- Хуки after-commit -------------------------------------------------------------------------


def after_commit(session: AsyncSession | Session, callback: AfterCommit) -> None:
    """Выполнить ``callback`` после успешного commit текущей транзакции сессии.

    При откате транзакции хук отбрасывается. Хуки выполняются по порядку регистрации в
    :func:`transaction` (или :func:`run_after_commit`) уже после commit, поэтому ошибка хука не
    откатывает данные — хук должен сам обрабатывать свои сбои (RT-002: событие потеряно → клиенты
    догонят изменения по ``change_log``).
    """
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    sync.info.setdefault(_PENDING, []).append(callback)


@event.listens_for(Session, "after_commit")
def _promote_hooks(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if pending:
        session.info.setdefault(_READY, []).extend(pending)


@event.listens_for(Session, "after_rollback")
def _drop_hooks(session: Session) -> None:
    session.info.pop(_PENDING, None)


async def run_after_commit(session: AsyncSession) -> None:
    """Выполнить хуки, чья транзакция уже зафиксирована."""
    ready: list[AfterCommit] = session.sync_session.info.pop(_READY, [])
    for callback in ready:
        result = callback()
        if inspect.isawaitable(result):
            await result


@asynccontextmanager
async def transaction(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Единица работы: сессия, commit при успехе, rollback при ошибке, затем хуки after-commit."""
    maker = sessionmaker or get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        await run_after_commit(session)


async def db_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: транзакция на запрос (commit до ответа — см. :data:`DbSession`)."""
    async with transaction() as session:
        yield session


#: Аннотация параметра эндпоинта: ``async def handler(session: DbSession)``.
DbSession = Annotated[AsyncSession, Depends(db_session, scope="function")]
