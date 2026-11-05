"""Фабрика приложения FastAPI и запуск Uvicorn (INF-002).

SPEC 13.1, 13.2: FastAPI + Uvicorn (ASGI), несколько реплик ``api`` за Nginx.
Роутеры доменов ``api/v1/*`` подключает трек API (``api/v1/__init__.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from estimator import health
from estimator.config import Settings, get_settings
from estimator.jobs.celery_app import queue_lengths
from estimator.logging import RequestIdMiddleware, configure_logging, get_logger
from estimator.metrics import REGISTRY, QueueLengthCollector, metrics_app
from estimator.redis_client import make_redis

log = get_logger(__name__)


def create_app(settings: Settings | None = None, probes: health.Probes | None = None) -> FastAPI:
    """Собрать приложение. Параметры подменяются в тестах."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    probes = probes if probes is not None else health.default_probes(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("app_started", app_env=settings.app_env.value, version=settings.app_version)
        yield
        await probes.close()
        await _app.state.redis.aclose()
        log.info("app_stopped")

    # Документация OpenAPI — только вне prod; источник правды — contracts/openapi.yaml
    docs = not settings.is_prod
    app = FastAPI(
        title="Приложение оценки проектов",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.probes = probes
    app.state.redis = make_redis(settings)
    app.include_router(health.router)
    app.mount("/metrics", metrics_app())
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestIdMiddleware)
    return app


_metrics_registered = False


def register_metrics(settings: Settings) -> None:
    """Подключить сборщик длины очередей Celery к реестру метрик (один раз на процесс)."""
    global _metrics_registered
    if not _metrics_registered:
        REGISTRY.register(QueueLengthCollector(lambda: queue_lengths(settings)))
        _metrics_registered = True


def app_factory() -> FastAPI:
    """Точка входа Uvicorn: ``uvicorn --factory estimator.main:app_factory``.

    Адрес, порт и доверенные прокси задаются ключами Uvicorn в образе
    (deploy/docker/api.Dockerfile),
    ``FORWARDED_ALLOW_IPS`` Uvicorn читает из окружения сам.
    """
    settings = get_settings()
    register_metrics(settings)
    return create_app(settings)
