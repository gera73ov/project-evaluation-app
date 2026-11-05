"""Блокировки и защита от подбора пароля (AUTH-005; FR-LOCK-01…05, R-07, Q-21).

Счётчики живут в Redis, а не в строке пользователя: так считаются и несуществующие логины,
и ответ для них одинаков (FR-LOCK-01, 14.2). Логин сравнивается без учёта регистра.

Как пользуется вход (AUTH-004, AUTH-006, AUTH-007)::

    gate = await guard.before_attempt(login, ip, superadmin=is_sa)
    if gate.code: → 429 gate.code с Retry-After = gate.retry_after (текст FR-LOCK-05)
    await asyncio.sleep(gate.delay_seconds)            # только для логина суперадминистратора
    … проверка пароля / TOTP …
    неудача:  result = await guard.record_failure(login, ip, superadmin=is_sa)
              записать result.events в аудит; await asyncio.sleep(result.delay_seconds)
    успех (пароль и, если нужен, TOTP): await guard.record_success(login, ip, superadmin=is_sa)

Неудачный TOTP — такая же неудачная попытка (FR-LOCK-03).

Ключи Redis (``login`` — в нижнем регистре):

* ``lock:{login}:{ip}`` — блок пары на ``lock_minutes`` (14.2);
* ``lockfail:{login}:{ip}`` — неудачи пары подряд; живёт ``lock_minutes`` после последней;
* ``lockhour:{login}`` — неудачи по логину за час с адресами (тревога > 20 с разных адресов);
* ``lockburst:{login}`` — тревога о всплеске уже отправлена в этот час;
* ``sadelay:{ip}``, ``sadelay_until:{ip}`` — растущая задержка для IP (FR-LOCK-04);
* ``safail:{login}`` — неудачи подряд по логину суперадминистратора;
* ``rl:login_ip:{ip}`` — 20 попыток в минуту с IP, затем 429 на 5 минут (FR-LOCK-02, SEC-008).
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis

from estimator.security.ratelimit import LIMITS, RateLimiter

#: Тревога ИБ, если по одному логину за час больше стольких неудач с разных адресов (FR-LOCK-01).
BURST_THRESHOLD = 20
BURST_WINDOW_SECONDS = 3600
#: Сколько последних неудач по логину хранить для подсчёта всплеска (защита памяти Redis).
BURST_KEEP = 1000
#: Тревога после стольких неудач подряд по логину суперадминистратора (FR-LOCK-04).
SUPERADMIN_ALERT_EVERY = 5
SUPERADMIN_MAX_DELAY = 60
#: Сколько помнить неудачи суперадминистратора без новых попыток.
SUPERADMIN_MEMORY_SECONDS = 24 * 3600

# KEYS[1] — lockhour:{login}; ARGV: сейчас (мс), окно (мс), член «ip|случайное», сколько хранить.
# Ответ: {неудач за окно, различных адресов}.
_BURST_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local keep = tonumber(ARGV[4])
local count = redis.call('ZCARD', KEYS[1])
if count > keep then
  redis.call('ZREMRANGEBYRANK', KEYS[1], 0, count - keep - 1)
  count = keep
end
redis.call('PEXPIRE', KEYS[1], window)
local seen = {}
local distinct = 0
for _, member in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  local ip = string.match(member, '^(.*)|[^|]*$')
  if ip and not seen[ip] then
    seen[ip] = true
    distinct = distinct + 1
  end
end
return {count, distinct}
"""


@dataclass(frozen=True)
class LockoutPolicy:
    """Параметры ``security.lockout`` (contracts/settings.schema.json)."""

    max_failures: int = 5
    lock_minutes: int = 15

    @classmethod
    def from_setting(cls, value: Mapping[str, Any] | None) -> LockoutPolicy:
        if not value:
            return cls()
        return cls(int(value["max_failures"]), int(value["lock_minutes"]))

    @property
    def lock_seconds(self) -> int:
        return self.lock_minutes * 60


@dataclass(frozen=True)
class Event:
    """Событие для журнала аудита (contracts/audit-events.yaml); пишет вызывающий код."""

    type: str
    details: dict[str, int]


@dataclass(frozen=True)
class Gate:
    """Можно ли проверять учётные данные. ``code`` — код ошибки 429 или ``None``."""

    code: str | None = None
    retry_after: int = 0
    delay_seconds: float = 0.0
    lock_minutes: int = 0  # для текста «повторите через N минут» (FR-LOCK-05)


@dataclass(frozen=True)
class FailureResult:
    locked: bool = False
    delay_seconds: int = 0
    events: tuple[Event, ...] = field(default_factory=tuple)


def normalize_login(login: str) -> str:
    return login.strip().lower()


def superadmin_delay(consecutive: int) -> int:
    """1, 2, 4, 8 … 60 с после каждой неудачи (FR-LOCK-04)."""
    if consecutive <= 0:
        return 0
    return min(2 ** min(consecutive - 1, 6), SUPERADMIN_MAX_DELAY)


class LoginGuard:
    """Блокировки пары «логин + IP», лимит попыток с IP и задержка для суперадминистраторов."""

    def __init__(
        self,
        redis: Redis,
        policy: LockoutPolicy | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis
        self.policy = policy or LockoutPolicy()
        self._clock = clock
        self._limiter = RateLimiter(redis, clock)
        self._burst = redis.register_script(_BURST_SCRIPT)

    async def before_attempt(self, login: str, ip: str, *, superadmin: bool) -> Gate:
        """Учесть попытку входа с IP и проверить блокировку пары (до проверки пароля)."""
        login = normalize_login(login)
        decision = await self._limiter.hit(LIMITS["login_ip"], ip)
        if not decision.allowed:
            return Gate(code="RATE_LIMITED", retry_after=decision.retry_after)
        if superadmin:
            wait_ms = await self._redis.pttl(f"sadelay_until:{ip}")
            return Gate(delay_seconds=max(wait_ms, 0) / 1000)
        lock_ms = await self._redis.pttl(f"lock:{login}:{ip}")
        if lock_ms > 0:
            return Gate(
                code="LOGIN_LOCKED",
                retry_after=max(1, -(-lock_ms // 1000)),
                lock_minutes=self.policy.lock_minutes,
            )
        return Gate()

    async def record_failure(self, login: str, ip: str, *, superadmin: bool) -> FailureResult:
        """Неудачный пароль или TOTP. Возвращает события аудита и задержку ответа."""
        login = normalize_login(login)
        events: list[Event] = []
        events.extend(await self._burst_check(login, ip))
        if superadmin:
            return await self._superadmin_failure(login, ip, events)
        key = f"lockfail:{login}:{ip}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self.policy.lock_seconds)
            failures, _ = await pipe.execute()
        if failures < self.policy.max_failures:
            return FailureResult(events=tuple(events))
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(f"lock:{login}:{ip}", 1, ex=self.policy.lock_seconds)
            pipe.delete(key)
            await pipe.execute()
        events.append(
            Event(
                "auth.lockout.pair_locked",
                {"failures": int(failures), "minutes": self.policy.lock_minutes},
            )
        )
        return FailureResult(locked=True, events=tuple(events))

    async def record_success(self, login: str, ip: str, *, superadmin: bool) -> None:
        """Успешный вход (пароль и TOTP): сбросить счётчики пары и задержку (FR-LOCK-01)."""
        login = normalize_login(login)
        keys = [f"lockfail:{login}:{ip}", f"lock:{login}:{ip}"]
        if superadmin:
            keys += [f"safail:{login}", f"sadelay:{ip}", f"sadelay_until:{ip}"]
        await self._redis.delete(*keys)

    async def _superadmin_failure(self, login: str, ip: str, events: list[Event]) -> FailureResult:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(f"sadelay:{ip}")
            pipe.expire(f"sadelay:{ip}", SUPERADMIN_MEMORY_SECONDS)
            pipe.incr(f"safail:{login}")
            pipe.expire(f"safail:{login}", SUPERADMIN_MEMORY_SECONDS)
            ip_failures, _, login_failures, _ = await pipe.execute()
        delay = superadmin_delay(int(ip_failures))
        await self._redis.set(f"sadelay_until:{ip}", 1, px=delay * 1000)
        events.append(
            Event(
                "auth.lockout.superadmin_delay",
                {"delay_seconds": delay, "consecutive_failures": int(login_failures)},
            )
        )
        if int(login_failures) % SUPERADMIN_ALERT_EVERY == 0:
            events.append(
                Event(
                    "security.superadmin_login_failures",
                    {"consecutive_failures": int(login_failures)},
                )
            )
        return FailureResult(delay_seconds=delay, events=tuple(events))

    async def _burst_check(self, login: str, ip: str) -> list[Event]:
        now_ms = int(self._clock() * 1000)
        count, distinct = await self._burst(
            keys=[f"lockhour:{login}"],
            args=[
                now_ms,
                BURST_WINDOW_SECONDS * 1000,
                f"{ip}|{secrets.token_hex(6)}",
                BURST_KEEP,
            ],
        )
        if count <= BURST_THRESHOLD or distinct < 2:
            return []
        first = await self._redis.set(f"lockburst:{login}", 1, nx=True, ex=BURST_WINDOW_SECONDS)
        if not first:
            return []
        return [
            Event(
                "security.login_failures_burst",
                {"failures_hour": int(count), "distinct_ips": int(distinct)},
            )
        ]
