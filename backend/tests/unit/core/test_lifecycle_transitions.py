"""CORE-011: таблица переходов сервиса совпадает с диаграммой 4.2 в permissions.yaml (D-04)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from estimator.services.projects import lifecycle

pytestmark = [pytest.mark.spec("4.2"), pytest.mark.spec("FR-PRJ-05")]

CONTRACT = Path(__file__).resolve().parents[4] / "contracts" / "permissions.yaml"


def test_transitions_match_contract() -> None:
    gates = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["derived_status_gates"]
    [d04] = [g for g in gates if g["id"] == "D-04"]
    expected = {frm: set(to) for frm, to in d04["transitions"].items()}
    actual = {frm.value: {t.value for t in to} for frm, to in lifecycle.TRANSITIONS.items()}
    assert actual == expected


def test_only_cancel_needs_reason() -> None:
    pairs = [(f, t) for f, ts in lifecycle.TRANSITIONS.items() for t in ts]
    assert [(f.value, t.value) for f, t in pairs if lifecycle.is_cancel(f, t)] == [
        ("estimation", "archived")
    ]
