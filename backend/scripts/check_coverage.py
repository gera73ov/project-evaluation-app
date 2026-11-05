"""Пороги покрытия NFR-MNT-01 сверх общего ``fail_under = 80`` (INF-005).

Расчётный модуль ``domain/calc`` и модуль прав ``security/authz`` — 100 % ветвлений и строк.
Читает ``coverage.json`` (``pytest --cov --cov-report=json``). Пока в модуле нет кода,
проверять нечего — порог начнёт действовать с первой строкой.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

STRICT = ("src/estimator/domain/calc/", "src/estimator/security/authz/")


def violations(report: dict) -> list[str]:
    problems = []
    for path, data in report.get("files", {}).items():
        norm = path.replace("\\", "/")
        if not any(prefix in norm for prefix in STRICT):
            continue
        s = data["summary"]
        branches_missed = s.get("num_branches", 0) - s.get("covered_branches", 0)
        if s.get("missing_lines", 0) or branches_missed:
            problems.append(
                f"{norm}: не покрыто строк {s.get('missing_lines', 0)}, "
                f"ветвлений {branches_missed} (нужно 100 %, NFR-MNT-01)"
            )
    return problems


def main(argv: list[str]) -> int:
    report = json.loads(Path(argv[1] if len(argv) > 1 else "coverage.json").read_text())
    problems = violations(report)
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print("check_coverage: domain/calc и security/authz — 100 %")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
