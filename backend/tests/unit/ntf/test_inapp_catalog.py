"""NTF-003: каталог видов в коде совпадает с contracts/notifications.yaml (NTF-001)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from estimator.notifications import inapp

CONTRACT = Path(__file__).resolve().parents[4] / "contracts" / "notifications.yaml"

pytestmark = pytest.mark.spec("FR-NOTIF-01")


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_kinds_match_contract() -> None:
    kinds = _contract()["kinds"]
    assert set(inapp.KINDS) == set(kinds)
    for name, spec in kinds.items():
        mine = inapp.KINDS[name]
        assert (mine.cls, mine.cq_related, mine.store) == (
            spec["class"],
            spec["cq_related"],
            spec["store"],
        ), name


def test_classes_match_contract() -> None:
    classes = _contract()["classes"]
    assert {k: dict(v) for k, v in inapp.CLASS_STATUSES.items()} == {
        k: v["statuses"] for k, v in classes.items()
    }
