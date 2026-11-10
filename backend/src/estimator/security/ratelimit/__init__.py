"""Ограничение частоты запросов (SEC-008; SEC-WEB-07, FR-LOCK-02, 15.2 ``/remind``).

Скользящее окно в Redis (сортированное множество отметок времени, атомарно скриптом Lua):

* :data:`LIMITS` — лимиты SPEC: 300 изменяющих запросов в минуту, 30 экспортов в час,
  60 сообщений в минуту на пользователя; 20 попыток входа в минуту с IP с блоком на 5 минут;
  «Напомнить не начавшим» — раз в сутки на проект;
* :class:`RateLimiter` — универсальный API для доменных лимитов: ``await limiter.hit(limit, id)``;
* :func:`rate_limit` — зависимость FastAPI: превышение → 429 с ``Retry-After``;
* :func:`add_listener` — подписка на превышения. Аудит ``security.rate_limited`` пишут места
  проверки (``rate_limit``, сессии, вход) через ``security/audit/security_events`` (SEC-010).
"""

from __future__ import annotations

from estimator.security.ratelimit.limiter import (
    LIMITS,
    Decision,
    Limit,
    RateLimitedError,
    RateLimiter,
    add_listener,
    rate_limit,
    remove_listener,
)

__all__ = [
    "LIMITS",
    "Decision",
    "Limit",
    "RateLimitedError",
    "RateLimiter",
    "add_listener",
    "rate_limit",
    "remove_listener",
]
