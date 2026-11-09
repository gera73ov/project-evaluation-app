"""Лимитер со скользящим окном в Redis (SEC-008)."""

from __future__ import annotations

import math
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from estimator.logging import get_logger
from estimator.redis_client import get_redis

log = get_logger(__name__)

KEY_PREFIX = "rl"

# KEYS[1] — окно (ZSET отметок времени, мс), KEYS[2] — блок после превышения.
# ARGV: сейчас (мс), длина окна (мс), лимит, длительность блока (мс, 0 — без блока), член ZSET.
# Ответ: {1, осталось} — разрешено и учтено; {0, через сколько мс повторить} — отказ.
_SCRIPT = """
local blocked = redis.call('PTTL', KEYS[2])
if blocked > 0 then return {0, blocked} end
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local block = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[5])
  redis.call('PEXPIRE', KEYS[1], window)
  return {1, limit - count - 1}
end
if block > 0 then
  redis.call('SET', KEYS[2], '1', 'PX', block)
  return {0, block}
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry = tonumber(oldest[2]) + window - now
if retry < 1 then retry = 1 end
return {0, retry}
"""


@dataclass(frozen=True)
class Limit:
    """Лимит: не больше ``max_hits`` за ``window_seconds``.

    ``block_seconds`` — после превышения отказывать столько секунд, даже если окно освободилось
    (FR-LOCK-02: «затем ответ 429 на 5 минут»). ``error_code`` — код ответа (contracts/errors.yaml).
    """

    name: str
    max_hits: int
    window_seconds: int
    block_seconds: int = 0
    error_code: str = "RATE_LIMITED"


#: Лимиты SPEC. Имена совпадают с ``details.limit`` события ``security.rate_limited``.
LIMITS: dict[str, Limit] = {
    limit.name: limit
    for limit in (
        Limit("mutations", 300, 60),  # SEC-WEB-07, на пользователя
        Limit("exports", 30, 3600),  # SEC-WEB-07, на пользователя
        Limit("messages", 60, 60),  # SEC-WEB-07, на пользователя
        Limit("login_ip", 20, 60, block_seconds=300),  # FR-LOCK-02, на IP
        # GET /auth/options (CR-001) — не попытка входа: экран входа спрашивает режим при каждом
        # открытии, и за NAT офиса общий с login_ip бюджет блокировал бы вход всем (CR-004)
        Limit("auth_options", 120, 60),  # на IP, без блока
        Limit("remind", 1, 86400, error_code="REMIND_TOO_OFTEN"),  # 15.2, на проект
    )
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0  # секунды, целое вверх; > 0 только при отказе
    remaining: int = 0


Listener = Callable[[Limit, str, Decision], Awaitable[None]]
_listeners: list[Listener] = []


def add_listener(listener: Listener) -> None:
    """Подписаться на превышения (аудит ``security.rate_limited`` подключают SEC-004/SEC-010)."""
    _listeners.append(listener)


def remove_listener(listener: Listener) -> None:
    _listeners.remove(listener)


class RateLimitedError(HTTPException):
    """Ответ 429 с ``Retry-After`` (SEC-WEB-07). Тело в формате RFC 9457 строит API-003."""

    def __init__(self, limit: Limit, retry_after: int) -> None:
        super().__init__(
            status_code=429,
            detail={"code": limit.error_code, "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
        self.limit = limit
        self.retry_after = retry_after


class RateLimiter:
    """Скользящее окно в Redis; ``clock`` подменяется в тестах."""

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock
        self._script = redis.register_script(_SCRIPT)

    @staticmethod
    def keys(limit: Limit, identity: str) -> tuple[str, str]:
        return (
            f"{KEY_PREFIX}:{limit.name}:{identity}",
            f"{KEY_PREFIX}:block:{limit.name}:{identity}",
        )

    async def hit(self, limit: Limit, identity: str) -> Decision:
        """Учесть одно действие. При отказе действие не учитывается и слушатели уведомляются."""
        now_ms = int(self._clock() * 1000)
        allowed, value = await self._script(
            keys=list(self.keys(limit, identity)),
            args=[
                now_ms,
                limit.window_seconds * 1000,
                limit.max_hits,
                limit.block_seconds * 1000,
                f"{now_ms}-{secrets.token_hex(6)}",
            ],
        )
        if allowed:
            return Decision(True, remaining=int(value))
        decision = Decision(False, retry_after=max(1, math.ceil(int(value) / 1000)))
        log.info("rate_limited", limit=limit.name, retry_after=decision.retry_after)
        for listener in list(_listeners):
            try:
                await listener(limit, identity, decision)
            except Exception:  # сбой подписчика не отменяет ответ 429
                log.exception("rate_limit_listener_failed", limit=limit.name)
        return decision

    async def check(self, limit: Limit, identity: str) -> None:
        """Учесть действие или выбросить :class:`RateLimitedError`."""
        decision = await self.hit(limit, identity)
        if not decision.allowed:
            raise RateLimitedError(limit, decision.retry_after)

    async def reset(self, limit: Limit, identity: str) -> None:
        await self._redis.delete(*self.keys(limit, identity))


def get_rate_limiter(redis: Redis = Depends(get_redis)) -> RateLimiter:  # noqa: B008
    return RateLimiter(redis)


def client_ip(request: Request) -> str:
    """IP клиента. За Nginx его подставляет Uvicorn по ``X-Forwarded-For`` (FORWARDED_ALLOW_IPS)."""
    return request.client.host if request.client else "unknown"


def rate_limit(
    name: str, identity: Callable[[Request], str | None] = client_ip
) -> Callable[..., Awaitable[None]]:
    """Зависимость FastAPI: ``dependencies=[Depends(rate_limit("exports", by_user))]``.

    ``identity`` возвращает, по чему считать (id пользователя, IP, id проекта); ``None`` —
    не ограничивать этот запрос (например, анонимный запрос к лимиту «на пользователя»).
    """
    limit = LIMITS[name]

    async def dependency(
        request: Request,
        limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
    ) -> None:
        who = identity(request)
        if who is not None:
            await limiter.check(limit, who)

    return dependency
