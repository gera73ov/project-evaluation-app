"""INF-005: порог 100 % для domain/calc и security/authz (NFR-MNT-01)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.spec("NFR-MNT-01")

_spec = importlib.util.spec_from_file_location(
    "check_coverage", Path(__file__).parents[3] / "scripts" / "check_coverage.py"
)
assert _spec
assert _spec.loader
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def _file(missing: int, branches: int, covered: int) -> dict:
    return {
        "summary": {
            "missing_lines": missing,
            "num_branches": branches,
            "covered_branches": covered,
        }
    }


def test_strict_modules_need_full_coverage(tmp_path: Path) -> None:
    report = {
        "files": {
            "src/estimator/domain/calc/pert.py": _file(0, 10, 9),
            "src/estimator/security/authz/engine.py": _file(1, 0, 0),
            "src/estimator/services/tree/x.py": _file(5, 10, 1),  # общий порог 80 % — не здесь
        }
    }
    problems = cc.violations(report)
    assert len(problems) == 2
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report))
    assert cc.main(["x", str(path)]) == 1


def test_full_coverage_passes(tmp_path: Path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"files": {"src/estimator/domain/calc/a.py": _file(0, 4, 4)}}))
    assert cc.main(["x", str(path)]) == 0
