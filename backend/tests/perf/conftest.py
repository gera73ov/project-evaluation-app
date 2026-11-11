"""Фикстуры замеров производительности (DB-013, EXP-013): приложение целиком и мир
пользователей — как у тестов ИБ."""

from tests.integration.auth.conftest import api, clock, encryption_key
from tests.integration.core.conftest import events, world

__all__ = ["api", "clock", "encryption_key", "events", "world"]
