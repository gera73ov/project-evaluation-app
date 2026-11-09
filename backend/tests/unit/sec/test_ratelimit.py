"""SEC-008: лимиты частоты SEC-WEB-07 и FR-LOCK-02 — превышение даёт 429 с Retry-After."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI
from redis.asyncio import Redis

from estimator.security.ratelimit import (
    LIMITS,
    Decision,
    Limit,
    RateLimitedError,
    RateLimiter,
    add_listener,
    rate_limit,
    remove_listener,
)

pytestmark = [pytest.mark.spec("SEC-WEB-07"), pytest.mark.integration]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _id() -> str:
    return f"t-{uuid.uuid4()}"


@pytest.mark.parametrize(
    ("name", "max_hits", "window"),
    [("mutations", 300, 60), ("exports", 30, 3600), ("messages", 60, 60)],
)
async def test_spec_limits_per_user(
    redis_client: Redis, name: str, max_hits: int, window: int
) -> None:
    limit = LIMITS[name]
    assert (limit.max_hits, limit.window_seconds) == (max_hits, window)
    clock = Clock()
    limiter = RateLimiter(redis_client, clock)
    user = _id()
    for i in range(max_hits):
        decision = await limiter.hit(limit, user)
        assert decision.allowed
        assert decision.remaining == max_hits - i - 1
    denied = await limiter.hit(limit, user)
    assert not denied.allowed
    assert denied.retry_after == window
    # другой пользователь не затронут
    assert (await limiter.hit(limit, _id())).allowed
    # окно скользит: через половину окна всё ещё отказ, после окна — снова можно
    clock.now += window / 2
    assert (await limiter.hit(limit, user)).retry_after == window // 2
    clock.now += window / 2 + 0.001
    assert (await limiter.hit(limit, user)).allowed


async def test_sliding_window_frees_oldest_first(redis_client: Redis) -> None:
    clock = Clock()
    limiter = RateLimiter(redis_client, clock)
    limit = Limit("t_window", 3, 10)
    who = _id()
    for _ in range(3):  # отметки t = 0, 4, 8
        assert (await limiter.hit(limit, who)).allowed
        clock.now += 4
    clock.now -= 4
    # t = 8: в окне отметки 0, 4, 8 → отказ, первая уйдёт в t = 10
    assert (await limiter.hit(limit, who)).retry_after == 2
    clock.now += 2.001
    assert (await limiter.hit(limit, who)).allowed
    assert not (await limiter.hit(limit, who)).allowed


@pytest.mark.spec("FR-LOCK-02")
async def test_login_ip_limit_blocks_for_five_minutes(redis_client: Redis) -> None:
    limit = LIMITS["login_ip"]
    assert (limit.max_hits, limit.window_seconds, limit.block_seconds) == (20, 60, 300)
    clock = Clock()
    limiter = RateLimiter(redis_client, clock)
    ip = _id()
    for _ in range(20):
        assert (await limiter.hit(limit, ip)).allowed
    first = await limiter.hit(limit, ip)
    assert not first.allowed
    assert first.retry_after == 300
    # окно освободилось, но блок 5 минут продолжается (TTL блока — время Redis)
    clock.now += 120
    again = await limiter.hit(limit, ip)
    assert not again.allowed
    assert 295 <= again.retry_after <= 300
    await limiter.reset(limit, ip)
    assert (await limiter.hit(limit, ip)).allowed


async def test_domain_limit_once_a_day_per_project(redis_client: Redis) -> None:
    limit = LIMITS["remind"]
    clock = Clock()
    limiter = RateLimiter(redis_client, clock)
    project = str(uuid.uuid4())
    await limiter.check(limit, project)
    clock.now += 3600
    with pytest.raises(RateLimitedError) as err:
        await limiter.check(limit, project)
    assert err.value.status_code == 429
    assert err.value.detail == {"code": "REMIND_TOO_OFTEN", "retry_after": 82800}
    assert err.value.headers == {"Retry-After": "82800"}
    await limiter.check(limit, str(uuid.uuid4()))


async def test_listener_gets_denials_and_failures_do_not_break(redis_client: Redis) -> None:
    seen: list[tuple[str, str, Decision]] = []

    async def listener(limit: Limit, identity: str, decision: Decision) -> None:
        seen.append((limit.name, identity, decision))

    async def broken(_limit: Limit, _identity: str, _decision: Decision) -> None:
        raise RuntimeError("audit down")

    add_listener(broken)
    add_listener(listener)
    try:
        limiter = RateLimiter(redis_client, Clock())
        limit = Limit("t_listen", 1, 60)
        who = _id()
        await limiter.hit(limit, who)
        assert seen == []
        denied = await limiter.hit(limit, who)
        assert seen == [("t_listen", who, denied)]
    finally:
        remove_listener(listener)
        remove_listener(broken)


async def test_fastapi_dependency_returns_429_with_retry_after(redis_client: Redis) -> None:
    app = FastAPI()
    app.state.redis = redis_client
    user = _id()

    def by_header(request) -> str | None:  # type: ignore[no-untyped-def]
        return request.headers.get("x-test-user")

    @app.post("/export", dependencies=[Depends(rate_limit("exports", by_header))])
    async def export() -> dict[str, bool]:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(30):
            assert (await client.post("/export", headers={"x-test-user": user})).status_code == 200
        response = await client.post("/export", headers={"x-test-user": user})
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 3500
        assert response.json()["detail"]["code"] == "RATE_LIMITED"
        # без идентификатора лимит не применяется
        for _ in range(3):
            assert (await client.post("/export")).status_code == 200


async def test_default_identity_is_client_ip(redis_client: Redis) -> None:
    app = FastAPI()
    app.state.redis = redis_client
    limit_name = "login_ip"

    @app.post("/login", dependencies=[Depends(rate_limit(limit_name))])
    async def login() -> dict[str, bool]:
        return {"ok": True}

    ip = f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    await RateLimiter(redis_client).reset(LIMITS[limit_name], ip)
    transport = httpx.ASGITransport(app=app, client=(ip, 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        codes = [(await client.post("/login")).status_code for _ in range(21)]
    await RateLimiter(redis_client).reset(LIMITS[limit_name], ip)
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


async def test_auth_options_limit_is_separate_and_generous(redis_client: Redis) -> None:
    """CR-004: свой лимит экрана входа на IP, без пятиминутного блока login_ip."""
    limit = LIMITS["auth_options"]
    assert (limit.max_hits, limit.window_seconds, limit.block_seconds) == (120, 60, 0)
    clock = Clock()
    limiter = RateLimiter(redis_client, clock)
    ip = _id()
    for _ in range(120):
        assert (await limiter.hit(limit, ip)).allowed
    assert (await limiter.hit(LIMITS["login_ip"], ip)).allowed, "бюджет входа не тронут"
    denied = await limiter.hit(limit, ip)
    assert not denied.allowed
    assert denied.retry_after <= 60
    await limiter.reset(limit, ip)
    await limiter.reset(LIMITS["login_ip"], ip)


def test_limit_names_match_audit_contract() -> None:
    """Имена лимитов — значения ``details.limit`` события security.rate_limited."""
    import re
    from pathlib import Path

    import yaml

    contract = Path(__file__).resolve().parents[4] / "contracts" / "audit-events.yaml"
    events = yaml.safe_load(contract.read_text(encoding="utf-8"))
    spec = next(v for k, v in _walk(events) if k == "security.rate_limited")
    found = re.search(r"enum\[([^\]]+)\]", spec["details"]["limit"])
    assert found
    assert {n.strip() for n in found.group(1).split(",")} == set(LIMITS)


def _walk(node: object) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.append((str(key), value))
            out.extend(_walk(value))
    return out
