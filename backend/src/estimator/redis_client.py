"""Общий асинхронный клиент Redis процесса API (сессии, блокировки, лимиты частоты).

Клиент создаётся в :func:`estimator.main.create_app` и лежит в ``app.state.redis``;
обработчики получают его зависимостью :func:`get_redis`, тесты подменяют ``app.state.redis``.
Соединения открываются лениво, при первом запросе.
"""

from __future__ import annotations

from fastapi import Request
from redis.asyncio import Redis

from estimator.config import Settings


def make_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_timeout=settings.health_timeout_seconds,
        socket_connect_timeout=settings.health_timeout_seconds,
        decode_responses=False,
    )


def get_redis(request: Request) -> Redis:
    """Зависимость FastAPI: клиент Redis приложения."""
    return request.app.state.redis
