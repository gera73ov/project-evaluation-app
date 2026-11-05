"""AUTH-005: блокировка пары «логин + IP», лимит с IP, задержка для суперадминистраторов.

Сценарии TC-AUTH-03 и TC-AUTH-07 на уровне сервиса (SPEC 17.1).
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from estimator.auth.lockout import (
    BURST_THRESHOLD,
    LockoutPolicy,
    LoginGuard,
    superadmin_delay,
)

pytestmark = [pytest.mark.integration]


def _ip() -> str:
    n = uuid.uuid4().int
    return f"10.{n % 251}.{(n >> 8) % 251}.{(n >> 16) % 251}"


def _login() -> str:
    return f"I.Ivanov-{uuid.uuid4().hex[:8]}"


async def _fail(guard: LoginGuard, login: str, ip: str, *, superadmin: bool = False):  # type: ignore[no-untyped-def]
    gate = await guard.before_attempt(login, ip, superadmin=superadmin)
    if gate.code:
        return gate, None
    return gate, await guard.record_failure(login, ip, superadmin=superadmin)


@pytest.mark.tc("TC-AUTH-07")
@pytest.mark.spec("FR-LOCK-01")
async def test_pair_locked_after_five_failures_only_from_that_ip(redis_client: Redis) -> None:
    guard = LoginGuard(redis_client)
    login, ip_a, ip_b = _login(), _ip(), _ip()
    for i in range(4):
        _, result = await _fail(guard, login, ip_a)
        assert result is not None
        assert not result.locked, i
    _, fifth = await _fail(guard, login, ip_a)
    assert fifth is not None
    assert fifth.locked
    assert [e.type for e in fifth.events] == ["auth.lockout.pair_locked"]
    assert fifth.events[0].details == {"failures": 5, "minutes": 15}

    gate = await guard.before_attempt(login.upper(), ip_a, superadmin=False)
    assert gate.code == "LOGIN_LOCKED"
    assert 890 < gate.retry_after <= 900
    assert gate.lock_minutes == 15
    assert 890 < await redis_client.ttl(f"lock:{login.lower()}:{ip_a}") <= 900
    # с другого адреса владелец входит как обычно
    assert (await guard.before_attempt(login, ip_b, superadmin=False)).code is None


@pytest.mark.tc("TC-AUTH-07")
@pytest.mark.spec("FR-LOCK-01")
async def test_unknown_login_gets_same_lock(redis_client: Redis) -> None:
    """Сервис не знает, есть ли логин: несуществующий блокируется точно так же."""
    guard = LoginGuard(redis_client)
    known, unknown, ip = _login(), "no-such-" + _login(), _ip()
    results = {}
    for login in (known, unknown):
        for _ in range(5):
            await _fail(guard, login, ip)
        results[login] = await guard.before_attempt(login, ip, superadmin=False)
    assert results[known].code == results[unknown].code == "LOGIN_LOCKED"


@pytest.mark.spec("FR-LOCK-01")
async def test_success_resets_counter(redis_client: Redis) -> None:
    guard = LoginGuard(redis_client)
    login, ip = _login(), _ip()
    for _ in range(4):
        await _fail(guard, login, ip)
    await guard.record_success(login, ip, superadmin=False)
    for _ in range(4):
        _, result = await _fail(guard, login, ip)
        assert result is not None
        assert not result.locked


@pytest.mark.spec("FR-LOCK-01")
async def test_counter_and_lock_expire_with_lock_minutes(redis_client: Redis) -> None:
    guard = LoginGuard(redis_client, LockoutPolicy(max_failures=3, lock_minutes=1))
    login, ip = _login(), _ip()
    await _fail(guard, login, ip)
    assert 55 < await redis_client.ttl(f"lockfail:{login.lower()}:{ip}") <= 60
    await _fail(guard, login, ip)
    _, third = await _fail(guard, login, ip)
    assert third is not None
    assert third.locked
    assert third.events[0].details == {"failures": 3, "minutes": 1}
    assert await redis_client.exists(f"lockfail:{login.lower()}:{ip}") == 0
    # блок истёк (эмулируем удалением ключа) — счёт начинается заново
    await redis_client.delete(f"lock:{login.lower()}:{ip}")
    assert (await guard.before_attempt(login, ip, superadmin=False)).code is None
    _, again = await _fail(guard, login, ip)
    assert again is not None
    assert not again.locked


def test_policy_from_setting() -> None:
    assert LockoutPolicy.from_setting(None) == LockoutPolicy(5, 15)
    assert LockoutPolicy.from_setting({"max_failures": 7, "lock_minutes": 30}) == LockoutPolicy(
        7, 30
    )


@pytest.mark.tc("TC-AUTH-07")
@pytest.mark.spec("SEC-AUTH-07")
async def test_burst_alert_over_20_failures_an_hour_from_different_ips(
    redis_client: Redis,
) -> None:
    guard = LoginGuard(redis_client)
    login = _login()
    ips = [_ip() for _ in range(6)]
    alerts = []
    for n in range(BURST_THRESHOLD + 5):
        _, result = await _fail(guard, login, ips[n % len(ips)])
        if result is None:
            continue
        alerts += [(n, e) for e in result.events if e.type == "security.login_failures_burst"]
    # 21-я неудача (n = 20) — тревога, одна на час; учётка не блокируется целиком
    assert len(alerts) == 1
    n, event = alerts[0]
    assert n == BURST_THRESHOLD
    assert event.details == {"failures_hour": 21, "distinct_ips": 6}
    assert (await guard.before_attempt(login, _ip(), superadmin=False)).code is None


async def test_no_burst_alert_from_single_ip(redis_client: Redis) -> None:
    clock = Clock()
    guard = LoginGuard(redis_client, LockoutPolicy(max_failures=20, lock_minutes=1), clock=clock)
    login, ip = _login(), _ip()
    events = []
    for _ in range(25):
        result = await guard.record_failure(login, ip, superadmin=False)
        events += [e.type for e in result.events]
    assert "security.login_failures_burst" not in events


async def test_burst_window_is_one_hour(redis_client: Redis) -> None:
    clock = Clock()
    guard = LoginGuard(redis_client, clock=clock)
    login = _login()
    for _ in range(BURST_THRESHOLD):
        await guard.record_failure(login, _ip(), superadmin=False)
    clock.now += 3601  # старые неудачи вышли из окна
    result = await guard.record_failure(login, _ip(), superadmin=False)
    assert all(e.type != "security.login_failures_burst" for e in result.events)


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.spec("FR-LOCK-02")
async def test_ip_rate_limit_20_per_minute_then_429_for_5_minutes(redis_client: Redis) -> None:
    guard = LoginGuard(redis_client)
    ip = _ip()
    for _ in range(20):
        assert (await guard.before_attempt(_login(), ip, superadmin=False)).code is None
    gate = await guard.before_attempt(_login(), ip, superadmin=False)
    assert gate.code == "RATE_LIMITED"
    assert gate.retry_after == 300
    # лимит действует и для логина суперадминистратора
    assert (await guard.before_attempt(_login(), ip, superadmin=True)).code == "RATE_LIMITED"


@pytest.mark.tc("TC-AUTH-03")
@pytest.mark.spec("FR-LOCK-04")
async def test_superadmin_not_locked_delay_grows_and_alert_after_five(
    redis_client: Redis,
) -> None:
    guard = LoginGuard(redis_client)
    login, ip = "sa-" + _login(), _ip()
    delays, alerts = [], []
    for _ in range(10):
        gate = await guard.before_attempt(login, ip, superadmin=True)
        assert gate.code is None  # никогда не блокируется
        result = await guard.record_failure(login, ip, superadmin=True)
        assert not result.locked
        delays.append(result.delay_seconds)
        alerts += [
            e.details for e in result.events if e.type == "security.superadmin_login_failures"
        ]
        delay_events = [e for e in result.events if e.type == "auth.lockout.superadmin_delay"]
        assert delay_events[0].details["delay_seconds"] == result.delay_seconds
    assert delays == [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]
    assert alerts == [{"consecutive_failures": 5}, {"consecutive_failures": 10}]
    assert await redis_client.exists(f"lock:{login.lower()}:{ip}") == 0
    # параллельный запрос с того же IP ждёт остаток задержки
    wait = (await guard.before_attempt(login, ip, superadmin=True)).delay_seconds
    assert 55 < wait <= 60
    # успешный вход сбрасывает задержку и счётчик
    await guard.record_success(login, ip, superadmin=True)
    assert (await guard.before_attempt(login, ip, superadmin=True)).delay_seconds == 0
    result = await guard.record_failure(login, ip, superadmin=True)
    assert result.delay_seconds == 1


@pytest.mark.spec("FR-LOCK-04")
def test_superadmin_delay_sequence() -> None:
    assert [superadmin_delay(n) for n in range(0, 9)] == [0, 1, 2, 4, 8, 16, 32, 60, 60]
    assert superadmin_delay(1000) == 60
