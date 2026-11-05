"""QA-001 · маркеры трассировки и выгрузка «тест → требования» (SPEC 17.2а, PLAN 1.3 п. 8).

Тест помечается ID из SPEC: ``@pytest.mark.tc("TC-CALC-01")``, ``@pytest.mark.spec("BR-BR-02")``,
``@pytest.mark.gherkin("G-07")``. Сценарии ``.feature`` получают ``gherkin`` из тега ``@G-NN``
(``backend/tests/acceptance/conftest.py``). С ключом ``--traceability-json=PATH`` плагин при сборе
тестов пишет JSON для ``tools/traceability.py``:

    {"source": "backend",
     "tests": [{"nodeid": "...", "tc": [...], "spec": [...], "gherkin": [...]}]}

Формат ID проверяется сразу: опечатка в маркере роняет сбор тестов, а не теряется в отчёте.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

#: Маркер → регулярное выражение допустимого ID.
MARKERS: dict[str, re.Pattern[str]] = {
    "tc": re.compile(r"TC-[A-Z]+-\d{2}"),
    # ID требования (FR-TREE-24, BR-CALC-03, SEC-AUTHZ-04, NFR-MNT-01, Q-07) или раздел SPEC (15.2)
    "spec": re.compile(r"(?:[A-Z]+(?:-[A-Z]+)*-\d{2}(?:\.\.\d{2})?|(?:SPEC-)?\d+(?:\.\d+)*[а-я]?)"),
    "gherkin": re.compile(r"G-\d{2}"),
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--traceability-json",
        metavar="PATH",
        default=None,
        help="Записать маркеры tc/spec/gherkin собранных тестов в JSON (tools/traceability.py)",
    )


def item_ids(item: pytest.Item) -> dict[str, list[str]]:
    """ID трассировки теста по маркерам (с маркеров модуля, класса и функции)."""
    found: dict[str, list[str]] = {name: [] for name in MARKERS}
    for name, pattern in MARKERS.items():
        for mark in item.iter_markers(name=name):
            for value in mark.args:
                if not isinstance(value, str) or not pattern.fullmatch(value):
                    raise pytest.UsageError(
                        f"{item.nodeid}: маркер {name}({value!r}) не похож на ID SPEC"
                    )
                if value not in found[name]:
                    found[name].append(value)
    return found


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    records = [{"nodeid": item.nodeid, **item_ids(item)} for item in items]
    path = config.getoption("--traceability-json")
    # под pytest-xdist тесты собирает каждый воркер — файл пишет только основной процесс
    if path and not hasattr(config, "workerinput"):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"source": "backend", "tests": records}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
