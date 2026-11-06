"""Поиск денежных ключей в ответах REST и событиях WS (SEC-006; TC-SEC-03, SEC-AUTHZ-04).

``find_money_keys(data)`` возвращает JSON Pointer каждого денежного ключа на любой глубине;
пустой список — денег в ответе нет. Ключи — :data:`estimator.security.serialize.MONEY_KEYS`
(``rate``, ``cost``, ``currency``, ``exchange_rate``, ``money`` и остальные из R-MONEY-FIELDS).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from estimator.security.serialize import MONEY_KEYS


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def find_money_keys(data: Any, keys: frozenset[str] = MONEY_KEYS, _path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            path = f"{_path}/{_escape(str(key))}"
            if key in keys:
                found.append(path)
            found += find_money_keys(value, keys, path)
    elif isinstance(data, list | tuple):
        for i, value in enumerate(data):
            found += find_money_keys(value, keys, f"{_path}/{i}")
    return found


def assert_no_money(data: Any) -> None:
    found = find_money_keys(data)
    assert not found, f"денежные ключи в ответе: {found}"
