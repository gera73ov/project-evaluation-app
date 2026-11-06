"""Фикстуры тестов ИБ: клиент приложения и часы — общие с интеграционными тестами AUTH."""

from tests.integration.auth.conftest import api, clock, encryption_key

__all__ = ["api", "clock", "encryption_key"]
