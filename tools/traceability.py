#!/usr/bin/env python3
"""QA-001 · отчёт трассировки «требование → тест» (SPEC 17.2а, NFR-MNT-01, PLAN 1.3 п. 8).

Источник — маркеры тестов ``tc``, ``spec``, ``gherkin`` (backend/tests/plugins/traceability.py).
Скрипт собирает тесты бэкенда без запуска (``pytest --collect-only``), читает списки TC из
SPEC 17.1 и сценарии G-01…G-26 из SPEC 17.2 и пишет Markdown:

* TC-* SPEC 17.1 → тесты (и какие TC пока без тестов);
* G-NN → тесты;
* требования и разделы SPEC → тесты;
* ID в маркерах, которых нет в SPEC (опечатки).

Запуск из корня репозитория (только стандартная библиотека Python 3.12):

    python3 tools/traceability.py                     # отчёт в build/traceability.md
    python3 tools/traceability.py --json a.json ...   # из готовых выгрузок (backend, e2e)
    python3 tools/traceability.py --strict            # код 1, если в маркерах есть чужие ID

Сквозной отчёт в CI с порогами — задача QA-027.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec" / "SPEC.md"
DEFAULT_OUTPUT = ROOT / "build" / "traceability.md"


@dataclass
class SpecIndex:
    """Что из SPEC участвует в трассировке."""

    tc: dict[str, str]  # TC-ID → «что проверяет»
    gherkin: dict[str, str]  # G-NN → «Функция → Сценарий»
    text: str
    sections: set[str] = field(default_factory=set)

    def knows(self, kind: str, value: str) -> bool:
        if kind == "tc":
            return value in self.tc
        if kind == "gherkin":
            return value in self.gherkin
        section = value.removeprefix("SPEC-")
        if re.fullmatch(r"\d+(?:\.\d+)*[а-я]?", section):
            return section in self.sections
        base = value.split("..", 1)[0]
        return re.search(rf"(?<![\w-]){re.escape(base)}(?![\w])", self.text) is not None


def parse_spec(text: str) -> SpecIndex:
    """Достать TC из таблицы 17.1, сценарии из 17.2 и номера разделов."""
    sections = set(re.findall(r"^#{2,4} (\d+(?:\.\d+)*[а-я]?)\.", text, flags=re.MULTILINE))
    part_17_1 = _between(text, "### 17.1.", "### 17.2.")
    tc = dict(re.findall(r"^\| (TC-[A-Z]+-\d{2}) \| (.+?) \|$", part_17_1, flags=re.MULTILINE))
    part_17_2 = _between(text, "### 17.2.", "### 17.2а.")
    gherkin: dict[str, str] = {}
    feature = ""
    for line in part_17_2.splitlines():
        line = line.strip()
        if line.startswith("Функция:"):
            feature = line.removeprefix("Функция:").strip()
        elif line.startswith("Сценарий:"):
            scenario = line.removeprefix("Сценарий:").strip()
            gherkin[f"G-{len(gherkin) + 1:02d}"] = f"{feature} → {scenario}"
    return SpecIndex(tc=tc, gherkin=gherkin, text=text, sections=sections)


def _between(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def collect_backend() -> dict:
    """Собрать тесты бэкенда без запуска и вернуть выгрузку маркеров."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "backend.json"
        command = [
            "uv", "--directory", str(ROOT / "backend"), "run", "--frozen", "pytest",
            "--collect-only", "-q", "-p", "no:xdist", "-p", "no:cacheprovider",
            f"--traceability-json={out}",
        ]  # fmt: skip
        result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0 or not out.exists():
            sys.stderr.write(result.stdout[-4000:] + result.stderr[-4000:])
            raise SystemExit("не удалось собрать тесты бэкенда")
        return json.loads(out.read_text(encoding="utf-8"))


@dataclass
class Report:
    markdown: str
    unknown: list[tuple[str, str, str]]  # (вид, ID, тест)


def build_report(dumps: list[dict], spec: SpecIndex) -> Report:
    by_kind: dict[str, dict[str, list[str]]] = {
        kind: defaultdict(list) for kind in ("tc", "gherkin", "spec")
    }
    unknown: list[tuple[str, str, str]] = []
    total = 0
    for dump in dumps:
        source = dump.get("source", "?")
        for test in dump["tests"]:
            total += 1
            name = f"{source}: {test['nodeid']}" + (" (pending)" if test.get("pending") else "")
            for kind in by_kind:
                for value in test.get(kind, []):
                    by_kind[kind][value].append(name)
                    if not spec.knows(kind, value):
                        unknown.append((kind, value, name))

    lines = ["# Трассировка требований к тестам", ""]
    tc_covered = sum(1 for tc in spec.tc if by_kind["tc"].get(tc))
    g_covered = sum(1 for g in spec.gherkin if by_kind["gherkin"].get(g))
    pending = sum(1 for d in dumps for t in d["tests"] if t.get("pending"))
    lines += [
        f"Тестов собрано: {total}. С маркерами трассировки: "
        f"{sum(1 for d in dumps for t in d['tests'] if any(t.get(k) for k in by_kind))}.",
        "",
        f"- Тест-кейсы SPEC 17.1: {tc_covered} из {len(spec.tc)} имеют тесты.",
        f"- Сценарии SPEC 17.2: {g_covered} из {len(spec.gherkin)} имеют тесты "
        f"(шаги не реализованы — pending: {pending}).",
        f"- Требований и разделов SPEC в маркерах: {len(by_kind['spec'])}.",
        "",
        "## Тест-кейсы SPEC 17.1",
        "",
        "| ID | Что проверяет | Тесты |",
        "|---|---|---|",
    ]
    for tc, what in spec.tc.items():
        lines.append(f"| {tc} | {_cell(what, 90)} | {_tests(by_kind['tc'].get(tc))} |")
    lines += ["", "## Сценарии SPEC 17.2", "", "| ID | Сценарий | Тесты |", "|---|---|---|"]
    for g, title in spec.gherkin.items():
        lines.append(f"| {g} | {_cell(title, 90)} | {_tests(by_kind['gherkin'].get(g))} |")
    lines += ["", "## Требования и разделы SPEC", "", "| ID | Тесты |", "|---|---|"]
    for value in sorted(by_kind["spec"], key=_natural):
        lines.append(f"| {value} | {_tests(by_kind['spec'][value])} |")
    if unknown:
        lines += ["", "## ID, которых нет в SPEC", "", "| Маркер | ID | Тест |", "|---|---|---|"]
        lines += [f"| {k} | {v} | `{t}` |" for k, v, t in unknown]
    return Report(markdown="\n".join(lines) + "\n", unknown=unknown)


def _natural(value: str) -> list[object]:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", value)]


def _cell(text: str, limit: int) -> str:
    text = text.replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tests(names: list[str] | None) -> str:
    """Список тестов ячейки; варианты параметризации одного теста сворачиваются в «×N»."""
    if not names:
        return "**нет теста**"
    counts: dict[str, int] = {}
    for name in names:
        base = name.split("[", 1)[0]
        counts[base] = counts.get(base, 0) + 1
    return "<br>".join(f"`{n}`" + (f" ×{c}" if c > 1 else "") for n, c in counts.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", nargs="*", type=Path, help="готовые выгрузки маркеров")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true", help="ошибка, если ID нет в SPEC")
    args = parser.parse_args(argv)

    spec = parse_spec(SPEC.read_text(encoding="utf-8"))
    if args.json:
        dumps = [json.loads(p.read_text(encoding="utf-8")) for p in args.json]
    else:
        dumps = [collect_backend()]
    report = build_report(dumps, spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.markdown, encoding="utf-8")
    print(f"отчёт трассировки: {args.output}")
    for kind, value, test in report.unknown:
        print(f"нет в SPEC: {kind}({value}) — {test}", file=sys.stderr)
    return 1 if args.strict and report.unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
