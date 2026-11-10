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
from estimator.api import v1 as api_v1
from estimator.api.common.docs import docs_urls
from estimator.api.common.errors import install_error_handlers
from estimator.config import Settings, get_settings
from estimator.jobs.celery_app import queue_lengths
from estimator.logging import RequestIdMiddleware, configure_logging, get_logger
from estimator.metrics import (
    REGISTRY,
    QueueLengthCollector,
    RequestMetricsMiddleware,
    metrics_app,
)
from estimator.realtime import ws as realtime_ws
from estimator.realtime.runtime import Realtime
from estimator.redis_client import make_redis
from estimator.security.alerts import notify as alerts
from estimator.security.authz.routes import assert_routes_protected
from estimator.security.web.headers import SecurityHeadersMiddleware
from estimator.security.web.limits import BodySizeLimitMiddleware

log = get_logger(__name__)


def create_app(settings: Settings | None = None, probes: health.Probes | None = None) -> FastAPI:
    """Собрать приложение. Параметры подменяются в тестах."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    probes = probes if probes is not None else health.default_probes(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("app_started", app_env=settings.app_env.value, version=settings.app_version)
        await _app.state.realtime.start()
        yield
        await _app.state.realtime.stop()
        await probes.close()
        await _app.state.redis.aclose()
        log.info("app_stopped")

    # Документация OpenAPI — только на стендах (API-005)
    app = FastAPI(
        title="Приложение оценки проектов",
        version=settings.app_version,
        lifespan=lifespan,
        **docs_urls(settings),
    )
    app.state.settings = settings
    app.state.probes = probes
    app.state.redis = make_redis(settings)
    # Совместная работа (RT-003…RT-008): WebSocket /api/v1/ws, Redis pub/sub, присутствие
    app.state.realtime = Realtime(settings, app.state.redis)
    install_error_handlers(app)
    alerts.install()  # письма оповещений ИБ по событиям аудита (SEC-011)
    app.include_router(health.router)
    app.include_router(api_v1.router, prefix=api_v1.PREFIX)
    # WebSocket — не REST-маршрут: права проверяет сам эндпоинт на каждую команду (RT-003)
    app.include_router(realtime_ws.router, prefix=api_v1.PREFIX)
    # Запрещено по умолчанию: маршрут без обеспеченного права не даёт стартовать (SEC-AUTHZ-02)
    assert_routes_protected(app)
    app.mount("/metrics", metrics_app())
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestIdMiddleware)
    # Внешние слои: заголовки ставятся и на ответы-ошибки, лимит тела — до разбора запроса
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    # Самый внешний слой: время и код считаются и для ответов 413 и заголовков (INF-010)
    app.add_middleware(RequestMetricsMiddleware)
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
