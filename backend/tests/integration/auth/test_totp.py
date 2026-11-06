"""AUTH-006: окно ±1 шаг и защита от повтора (TC-AUTH-04)."""

from __future__ import annotations

import uuid

import pyotp
import pytest
from redis.asyncio import Redis

from estimator.auth.totp import TotpVerifier, generate_backup_codes, new_secret, provisioning_uri

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-AUTH-04"), pytest.mark.spec("FR-2FA-01")]

T0 = 1_800_000_000.0  # начало шага


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


async def test_window_and_replay(redis_client: Redis) -> None:
    clock = Clock()
    verifier = TotpVerifier(redis_client, clock)
    secret = new_secret()
    totp = pyotp.TOTP(secret)
    user = uuid.uuid4()
    assert not await verifier.verify(user, secret, totp.at(T0 - 60)), "два шага назад — нет"
    assert await verifier.verify(user, secret, totp.at(T0 - 30)), "соседний шаг принимается"
    assert not await verifier.verify(user, secret, totp.at(T0 - 30)), "повтор отклоняется"
    assert await verifier.verify(user, secret, totp.at(T0))
    assert not await verifier.verify(user, secret, totp.at(T0 - 30)), "откат на старый шаг — нет"
    assert await verifier.verify(user, secret, totp.at(T0 + 30))
    clock.now += 90
    assert not await verifier.verify(user, secret, totp.at(T0 + 30)), "повтор и после окна"
    assert not await verifier.verify(user, secret, "12345"), "неверный формат"
    other = uuid.uuid4()
    assert await verifier.verify(other, secret, totp.at(clock.now)), "шаги — по пользователю"


def test_uri_and_backup_codes() -> None:
    secret = new_secret()
    uri = provisioning_uri(secret, "i.ivanov")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "digits=6" in uri or "digits" not in uri
    codes = generate_backup_codes()
    assert len(codes) == len(set(codes)) == 10
    assert all(len(c) == 8 and c.isdigit() for c in codes)
