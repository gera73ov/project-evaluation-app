"""DB-002 · окружение Alembic (асинхронный движок asyncpg).

* Адрес и TLS — из :mod:`estimator.config` (``DATABASE_URL``, ``DATABASE_SSLMODE``),
  как у приложения.
* Если роль ``estimator_migrator`` уже получила права в этой базе (не первый прогон), соединение
  переключается на неё
  (``SET ROLE``): все таблицы, типы и функции принадлежат ей, а права ``estimator_app`` выдаются
  через ``ALTER DEFAULT PRIVILEGES`` первой миграции. На пустом кластере роли создаёт ревизия
  ``0001_base`` и сама переключается на migrator в конце.
* ``target_metadata`` — метаданные ORM: нужны ``alembic check`` и тесту сравнения схемы.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from estimator.config import get_settings
from estimator.db import roles
from estimator.db.models import metadata
from estimator.db.session import connect_args

config = context.config
target_metadata = metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Партиции журнала аудита создаёт периодическая задача, в ORM их нет.
    return not (type_ == "table" and reflected and name and name.startswith("audit_log_"))


def _configure(connection: Connection) -> None:
    connection.execute(text("SET TIME ZONE 'UTC'"))
    # Роль есть и уже получила права в этой базе (ревизия 0001 применена) — работаем от неё.
    # Роли кластерные, поэтому в новой базе роль может быть, а прав на public у неё ещё нет.
    migrator_ready = connection.execute(
        text(
            "SELECT has_schema_privilege(r.rolname, 'public', 'CREATE') "
            "FROM pg_roles r WHERE r.rolname = :r"
        ),
        {"r": roles.MIGRATOR},
    ).scalar()
    if migrator_ready:
        connection.execute(text(roles.set_role_sql(roles.MIGRATOR)))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=_include_object,
        compare_type=True,
        transaction_per_migration=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        poolclass=NullPool,
        connect_args=connect_args(settings),
    )
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_configure)
            await conn.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Офлайн-режим (--sql) не поддерживается: миграции выполняются на живой БД.")
asyncio.run(_run_online())
