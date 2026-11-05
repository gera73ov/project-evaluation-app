"""Общие фикстуры тестов бэкенда."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from estimator.config import get_settings

#: Адрес тестового Redis, например ``redis://127.0.0.1:6379/15``. Без него тесты с фикстурой
#: :func:`redis_client` пропускаются. Тесты не чистят базу: ключи у каждого теста свои
#: (случайные логины, IP, id), поэтому параллельные процессы xdist друг другу не мешают.
REDIS_ENV_VAR = "TEST_REDIS_URL"


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch):
    """Каждый тест читает окружение заново и не видит переменных разработчика."""
    for name in ("APP_ENV", "LOG_LEVEL", "APP_TIMEZONE", "TRUSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Клиент тестового Redis (``TEST_REDIS_URL``)."""
    url = os.environ.get(REDIS_ENV_VAR)
    if not url:
        pytest.skip(f"{REDIS_ENV_VAR} не задан")
    client = Redis.from_url(url)
    yield client
    await client.aclose()
