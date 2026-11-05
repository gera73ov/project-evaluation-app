"""Общие фикстуры тестов бэкенда."""

from __future__ import annotations

import pytest

from estimator.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch):
    """Каждый тест читает окружение заново и не видит переменных разработчика."""
    for name in ("APP_ENV", "LOG_LEVEL", "APP_TIMEZONE", "TRUSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
