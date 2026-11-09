"""Фикстуры API-тестов NTF: те же, что у CORE (приложение целиком, сессии, шина в памяти)."""

from tests.integration.core.conftest import (  # noqa: F401
    api,
    clock,
    encryption_key,
    events,
    world,
)
