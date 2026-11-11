"""FE-094 · установка «с нуля» для сценариев e2e/ad: пустая база и первый суперадминистратор.

Запуск из каталога backend, с теми же DATABASE_URL, REDIS_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/ad/reset.py            # пустая база + create-superadmin
    uv run --frozen python ../e2e/ad/reset.py --plain    # только пустая база (после сценариев)

Удаляет схемы ``public`` и ``audit`` со всеми данными, применяет миграции (``estimator migrate``),
закрывает соединения API и worker с базой (в них закэшированы типы старой схемы), очищает Redis
(сессии, лимиты входа, кэши) и выполняет ``estimator create-superadmin``. Печатает JSON с логином
и путём ссылки установки пароля; его читает ad.spec.ts. Сценарии e2e/ad идут последними (проект
``ad`` в playwright.config.ts, только при E2E_AD=1), поэтому остальным наборам сброс не мешает.
Только для dev и тестовых стендов: при APP_ENV, отличном от dev и test, — отказ.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys

CLI = [sys.executable, "-c", "from estimator.cli import main; main()"]


TERMINATE = (
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
)


async def terminate_others() -> None:
    """Закрыть соединения API и worker: asyncpg держит в них OID типов удалённой схемы. Пул с
    pre_ping откроет новые соединения при следующем запросе."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from estimator.config import get_settings

    engine = create_async_engine(get_settings().database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            await conn.execute(text(TERMINATE))
    finally:
        await engine.dispose()


async def wipe() -> None:
    from redis.asyncio import Redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from estimator.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            await conn.execute(text(TERMINATE))
            await conn.execute(text("DROP SCHEMA IF EXISTS audit CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()


def cli(*args: str) -> str:
    done = subprocess.run(  # noqa: S603  # nosec B603 — свой CLI, аргументы — константы сценария
        [*CLI, *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        sys.exit(f"estimator {' '.join(args)}: {done.stderr or done.stdout}")
    return done.stdout


def main() -> None:
    if os.environ.get("APP_ENV", "dev") not in ("dev", "test"):
        sys.exit("reset.py только для dev и тестовых стендов")
    asyncio.run(wipe())
    cli("migrate")
    asyncio.run(terminate_others())
    if "--plain" in sys.argv:
        print(json.dumps({"reset": True}))
        return
    login = f"e2e-fe-sa-{secrets.token_hex(3)}"
    out = cli("create-superadmin", "--login", login, "--email", f"{login}@example.test")
    link = re.search(r"https?://\S+", out)
    if link is None:
        sys.exit(f"нет ссылки в выводе create-superadmin: {out}")
    path = re.sub(r"^https?://[^/]+", "", link.group(0))
    print(json.dumps({"login": login, "link": path}))  # вывод читает ad.spec.ts


if __name__ == "__main__":
    main()
