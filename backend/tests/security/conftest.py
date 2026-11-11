"""Фикстуры тестов ИБ: клиент приложения и часы — общие с интеграционными тестами AUTH; мир
пользователей и шина событий — как у CORE (обходы TC-SEC-03, TC-SEC-07)."""

from tests.integration.auth.conftest import api, clock, encryption_key
from tests.integration.core.conftest import events, world

__all__ = ["api", "clock", "encryption_key", "events", "world"]
