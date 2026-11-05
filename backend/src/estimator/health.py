"""Проверки живости и готовности (INF-002).

NFR-MNT-05: ``/health/live`` и ``/health/ready`` (БД, Redis) доступны только из внутренней
сети: публичный Nginx их не проксирует (deploy/nginx). ``/health/live`` не трогает внешние
сервисы — по нему оркестратор решает, перезапускать ли процесс. ``/health/ready`` проверяет
PostgreSQL и Redis; при сбое отвечает 503 и не раскрывает текст ошибки.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from estimator.config import Settings
from estimator.logging import get_logger

HealthCheck = Callable[[], Awaitable[None]]

log = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["health"], include_in_schema=False)


class Probes:
    """Набор проверок готовности. Треки добавляют свои через :meth:`add`."""

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._closers: list[Callable[[], Awaitable[None]]] = []

    def add(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    def on_close(self, closer: Callable[[], Awaitable[None]]) -> None:
        self._closers.append(closer)

    @property
    def names(self) -> list[str]:
        return list(self._checks)

    async def run(self, limit_seconds: float) -> dict[str, str]:
        async def one(name: str, check: HealthCheck) -> tuple[str, str]:
            started = time.perf_counter()
            try:
                await asyncio.wait_for(check(), timeout=limit_seconds)
            except Exception as exc:  # noqa: BLE001 — любая ошибка = «не готов»
                log.warning(
                    "health_check_failed",
                    check=name,
                    error_type=type(exc).__name__,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                return name, "fail"
            return name, "ok"

        results = await asyncio.gather(*(one(n, c) for n, c in self._checks.items()))
        return dict(results)

    async def close(self) -> None:
        for closer in self._closers:
            await closer()


def default_probes(settings: Settings) -> Probes:
    """Проверки PostgreSQL и Redis по настройкам процесса."""
    probes = Probes()
    engine: AsyncEngine = create_async_engine(
        settings.database_url.get_secret_value(), pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_timeout=settings.health_timeout_seconds,
        socket_connect_timeout=settings.health_timeout_seconds,
    )

    async def check_db() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def check_redis() -> None:
        await redis.ping()

    probes.add("database", check_db)
    probes.add("redis", check_redis)
    probes.on_close(engine.dispose)
    probes.on_close(redis.aclose)
    return probes


@router.get("/live")
async def live() -> dict[str, str]:
    """Процесс жив и обслуживает запросы."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    """Готовность: PostgreSQL и Redis отвечают (NFR-MNT-05)."""
    probes: Probes = request.app.state.probes
    settings: Settings = request.app.state.settings
    checks = await probes.run(settings.health_timeout_seconds)
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "fail", "checks": checks}
