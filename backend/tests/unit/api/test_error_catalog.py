"""API-003: копия каталога кодов в коде совпадает с contracts/errors.yaml (API-001)."""

from __future__ import annotations

import pytest

from estimator.api.common.catalog import CATALOG, TYPE_BASE
from tests.unit._contracts import load_yaml

pytestmark = pytest.mark.spec("15.1")

CONTRACT = load_yaml("errors.yaml")


def test_type_base() -> None:
    assert CONTRACT["type_base"] == TYPE_BASE


def test_catalog_matches_contract() -> None:
    expected = {
        e["code"]: (e["status"], e["type"], e["title"], tuple(sorted(e.get("extensions") or {})))
        for e in CONTRACT["errors"]
    }
    actual = {c: (s.status, s.type, s.title, s.extensions) for c, s in CATALOG.items()}
    assert actual == expected
