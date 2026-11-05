"""DB-002: генератор UUID v7 (contracts/db/schema.md G-2, RFC 9562)."""

from __future__ import annotations

import time
import uuid

import pytest

from estimator.db import uuid7 as mod

pytestmark = pytest.mark.spec("NFR-MNT-02")


def test_version_and_variant() -> None:
    value = mod.uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_timestamp_is_current_time() -> None:
    before = time.time_ns() // 1_000_000
    value = mod.uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= mod.timestamp_ms(value) <= after + 1


def test_strictly_increasing_within_process() -> None:
    values = [mod.uuid7() for _ in range(10_000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_counter_overflow_moves_time_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_now_ms", lambda: 1_000)
    monkeypatch.setattr(mod, "_last_ms", -1)
    first = mod.uuid7()
    values = [mod.uuid7() for _ in range(5_000)]  # больше 4 096 значений счётчика за 1 мс
    assert values == sorted(values)
    assert mod.timestamp_ms(first) == 1_000
    assert mod.timestamp_ms(values[-1]) > 1_000


def test_clock_going_back_keeps_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_last_ms", -1)
    monkeypatch.setattr(mod, "_now_ms", lambda: 5_000)
    a = mod.uuid7()
    monkeypatch.setattr(mod, "_now_ms", lambda: 4_000)
    b = mod.uuid7()
    assert b > a


@pytest.mark.parametrize(("unix_ms", "counter"), [(-1, 0), (1 << 48, 0), (0, -1), (0, 1 << 12)])
def test_from_parts_rejects_out_of_range(unix_ms: int, counter: int) -> None:
    with pytest.raises(ValueError, match="вне диапазона"):
        mod.from_parts(unix_ms, counter, 0)


def test_timestamp_rejects_other_versions() -> None:
    with pytest.raises(ValueError, match="версии 7"):
        mod.timestamp_ms(uuid.uuid4())
