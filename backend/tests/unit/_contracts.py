"""Общие помощники тестов контрактов этапа 0: чтение SPEC и файлов из contracts/."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
SPEC_PATH = REPO / "docs" / "spec" / "SPEC.md"


@cache
def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def spec_table(heading: str, *, skip_header: bool = True) -> list[list[str]]:
    """Первая Markdown-таблица после заголовка `heading`, по строкам и ячейкам."""
    text = spec_text()
    lines = text[text.index(heading) :].splitlines()[1:]
    rows: list[list[str]] = []
    started = False
    for line in lines:
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            rows.append(cells)
        elif started:
            break
    return rows[1:] if skip_header else rows


@cache
def load_yaml(name: str) -> Any:
    return yaml.safe_load((CONTRACTS / name).read_text(encoding="utf-8"))


@cache
def load_json(name: str) -> Any:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
