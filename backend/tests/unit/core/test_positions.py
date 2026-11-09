"""CORE-014: дробные ключи позиций — порядок, вставка между соседями, рост длины."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from estimator.services.tree.positions import (
    FIRST,
    PositionError,
    key_between,
    keys_after,
    validate,
)

pytestmark = pytest.mark.spec("14.2")


def test_basics() -> None:
    assert key_between(None, None) == FIRST == "a0"
    assert key_between("a0", None) == "a1"
    assert key_between(None, "a0") == "Zz"
    mid = key_between("a0", "a1")
    assert "a0" < mid < "a1"


def test_appends_grow_logarithmically() -> None:
    keys = keys_after(None, 5000)
    assert keys == sorted(keys)
    assert len(set(keys)) == 5000
    assert max(len(k) for k in keys) <= 4  # a0…az, b00…bzz, c000…


def test_prepends_stay_ordered() -> None:
    keys = ["a0"]
    for _ in range(500):
        keys.insert(0, key_between(None, keys[0]))
    assert keys == sorted(keys)
    assert max(len(k) for k in keys) <= 4


@pytest.mark.parametrize("bad", ["", "a", "a00", "a10", "!", "A00000000000000000000000000"])
def test_invalid_keys(bad: str) -> None:
    with pytest.raises(PositionError):
        validate(bad)


def test_unordered() -> None:
    with pytest.raises(PositionError):
        key_between("a1", "a0")
    with pytest.raises(PositionError):
        key_between("a1", "a1")


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.integers(min_value=0, max_value=1000), st.booleans()), max_size=60))
def test_random_insertions_keep_order(ops: list[tuple[int, bool]]) -> None:
    keys: list[str] = []
    for where, _ in ops:
        i = where % (len(keys) + 1)
        before = keys[i - 1] if i > 0 else None
        after = keys[i] if i < len(keys) else None
        key = key_between(before, after)
        validate(key)
        if before is not None:
            assert before < key
        if after is not None:
            assert key < after
        keys.insert(i, key)
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_repeated_midpoint_between_neighbours() -> None:
    low, high = "a0", "a1"
    for _ in range(200):
        mid = key_between(low, high)
        assert low < mid < high
        high = mid
    assert len(high) < 220
