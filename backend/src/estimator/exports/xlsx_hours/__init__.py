"""EXP-004 · Excel «Часы» (FR-EXP-01, FR-EXP-03, FR-EXP-04, BR-MONEY-06, Q-36;
contracts/exports.yaml ``hours_xlsx``).

Листы «Оценка», «Допущения и риски», «Параметры». Строки «Оценки» — дерево в порядке позиций:
фаза → дисциплина → узлы; ветка «не нужно» и выключенная фаза — одной строкой. После фазы —
итог фазы, в конце — «Работы», «Управление проектом N %», «Итог E», «P80», «P90» и
«Цифра для КП». Значения, не формулы; текст экранируется (EXP-002); отметки — на всех листах.

:func:`estimate_workbook` строит и «С деньгами» (EXP-005): с ``money`` после «σ» добавляются
«Ставка», «Стоимость, ₽», «Стоимость, <валюта>». Без денег этих колонок нет совсем (TC-SEC-04).
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.domain import calc
from estimator.domain.calc._decimal import round_half_up
from estimator.domain.calc.model import PM_ROW
from estimator.exports import engine, marks
from estimator.exports.safe_values import Value, write_cell
from estimator.exports.source import Source, load, today

HOURS = "0.0"
MONEY = "#,##0"
DATA_ROW = marks.XLSX_DATA_ROW
BOLD = Font(bold=True)
QUOTE_FILL = PatternFill("solid", fgColor="FFF2CC")

FIGURE_LABEL = {"e": "E", "p80": "P80", "p90": "P90"}
LEVEL_LABEL = {"coarse": "Крупно", "medium": "Средне", "detailed": "Детально"}
BRANCH_LABEL = {
    "not_started": "не начато",
    "draft": "черновик",
    "done": "готово",
    "not_needed": "не нужно",
}
CATEGORY_LABEL = {
    "assumption": "Допущения",
    "constraint": "Ограничения",
    "risk": "Риски",
    "tech": "Технологии",
}


def _num(value: Decimal | None, places: int = 1) -> Decimal | None:
    return None if value is None else round_half_up(value, places)


def _put(
    sheet: Worksheet, row: int, values: Sequence[Value], formats: Sequence[str | None]
) -> None:
    for col, (value, fmt) in enumerate(zip(values, formats, strict=True), start=1):
        cell = write_cell(sheet.cell(row=row, column=col), value)
        if fmt and isinstance(value, Decimal | int):
            cell.number_format = fmt


@dataclass
class _Money:
    settings: calc.MoneySettings

    @property
    def currency(self) -> str:
        return self.settings.currency

    def rate(self, row: str | None) -> Decimal | None:
        return self.settings.rates.get(None if row in (None, PM_ROW) else row)

    def cost(self, e: Decimal, row: str | None) -> Decimal | None:
        rate = self.rate(row)
        return None if rate is None else round_half_up(e * rate)

    def cur(self, rub: Decimal | None) -> Decimal | None:
        return None if rub is None else round_half_up(rub / self.settings.exchange_rate)


class _Tree:
    """Узлы снимка: дети по позиции, названия фаз и дисциплин, пути."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.nodes = {n["id"]: n for n in payload["nodes"]}
        self.children: dict[str | None, list[dict[str, Any]]] = {}
        for n in payload["nodes"]:
            self.children.setdefault(n["parent_id"], []).append(n)
        for items in self.children.values():
            items.sort(key=lambda n: (n["position"], n["id"]))
        self.phase_names = {p["id"]: p["name"] for p in payload["phases"]}
        self.discipline_names = {d["id"]: d["name"] for d in payload["disciplines"]}
        self.types = payload.get("types", {})
        self.tags = payload.get("tags", {})

    def title(self, n: Mapping[str, Any]) -> str:
        if n["kind"] == "phase":
            return n["title"] or self.phase_names.get(n["phase_id"], "")
        if n["kind"] == "discipline":
            return n["title"] or self.discipline_names.get(n["discipline_id"] or "", "")
        return str(n["title"])

    def path(self, node_id: str) -> list[str]:
        out: list[str] = []
        cur: str | None = node_id
        while cur is not None and cur in self.nodes and len(out) < 50:
            out.append(self.title(self.nodes[cur]))
            cur = self.nodes[cur]["parent_id"]
        return out[::-1]


def _lines(n: Mapping[str, Any], tree: _Tree) -> tuple[str | None, str | None]:
    lines = [ln for ln in n.get("comment_lines") or [] if isinstance(ln, Mapping)]
    if not lines:
        return None, None
    texts = "\n".join(str(ln.get("text", "")) for ln in lines)
    labels = "\n".join(tree.tags.get(str(ln.get("tag_id")), "") for ln in lines)
    return texts, labels if labels.strip() else None


class _Estimate:
    """Лист «Оценка»."""

    def __init__(self, sheet: Worksheet, src: Source, money: _Money | None) -> None:
        self.sheet, self.src, self.money = sheet, src, money
        self.tree = _Tree(src.payload)
        self.results = src.result.tree.nodes
        self.status = {
            (b["phase_id"], b["discipline_id"]): b["status"] for b in src.payload["branch_status"]
        }
        self.row = DATA_ROW + 1  # строка DATA_ROW — заголовки колонок
        self.rows = 0
        cur = money.currency if money else ""
        self.header = ["Уровень", "Узел", "Тип", "×N", "O", "R", "P", "E", "σ"]
        self.formats: list[str | None] = [None, None, None, None, HOURS, HOURS, HOURS, HOURS, HOURS]
        if money:
            self.header += ["Ставка", "Стоимость, ₽", f"Стоимость, {cur}"]
            self.formats += [MONEY, MONEY, MONEY]
        self.header += ["Комментарий", "Метка", "Статус ветки", "Проверено"]
        self.formats += [None, None, None, None]

    def _write(
        self,
        level: int | None,
        title: str,
        *,
        kind: str | None = None,
        n: Mapping[str, Any] | None = None,
        e: Decimal | None = None,
        sigma: Decimal | None = None,
        cost: tuple[Decimal | None, Decimal | None, Decimal | None] | None = None,
        status: str | None = None,
        bold: bool = False,
        fill: PatternFill | None = None,
    ) -> None:
        texts = labels = None
        o = r = p = None
        multiplier: int | None = None
        if n is not None:
            texts, labels = _lines(n, self.tree)
            if n["kind"] not in ("phase", "discipline") or not self.tree.children.get(n["id"]):
                o, r, p = (None if n[k] is None else Decimal(n[k]) for k in ("o", "r", "p"))
                multiplier = n["multiplier"]
        values: list[Value] = [
            level,
            title,
            kind,
            multiplier,
            _num(o),
            _num(r),
            _num(p),
            _num(e),
            _num(sigma),
        ]
        if self.money:
            values += list(cost or (None, None, None))
        values += [
            texts,
            labels,
            status,
            self.src.reviewed.get(n["id"]) if n is not None else None,
        ]
        _put(self.sheet, self.row, values, self.formats)
        if level and level > 1:
            self.sheet.row_dimensions[self.row].outlineLevel = min(level - 1, 7)
            self.sheet.cell(row=self.row, column=2).alignment = Alignment(indent=level - 1)
        if bold or fill:
            for col in range(1, len(self.header) + 1):
                cell = self.sheet.cell(row=self.row, column=col)
                if bold:
                    cell.font = BOLD
                if fill:
                    cell.fill = fill
        self.row += 1
        self.rows += 1

    def _cost(self, n: Mapping[str, Any]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """Ставка дисциплины, стоимость (сумма округлённых листьев) и в валюте."""
        if not self.money:
            return None, None, None
        res = self.results.get(n["id"])
        if res is None or res.excluded:
            return None, None, None
        if res.is_leaf:
            rub = self.money.cost(res.totals.e, n["discipline_id"])
            rate = self.money.rate(n["discipline_id"])
        else:
            parts = [self._cost(c)[1] for c in self.tree.children.get(n["id"], [])]
            known = [x for x in parts if x is not None]
            rub = sum(known, Decimal(0)) if known else None
            rate = self.money.rate(n["discipline_id"]) if n["discipline_id"] else None
        return rate, rub, self.money.cur(rub)

    def _node(self, n: Mapping[str, Any], level: int) -> None:
        res = self.results.get(n["id"])
        e = res.totals.e if res and not res.excluded else None
        sigma = res.totals.sigma if res and not res.excluded else None
        kind = self.tree.types.get(n["type_id"] or "") if n["kind"] == "item" else None
        status = None
        if n["kind"] == "discipline":
            raw = self.status.get((n["phase_id"], n["discipline_id"]))
            status = BRANCH_LABEL.get(raw or "", raw)
        self._write(
            level,
            self.tree.title(n),
            kind=kind,
            n=n,
            e=e,
            sigma=sigma,
            cost=self._cost(n),
            status=status,
            bold=n["kind"] in ("phase", "discipline"),
        )
        if status == BRANCH_LABEL["not_needed"]:
            return
        for child in self.tree.children.get(n["id"], []):
            self._node(child, level + 1)

    def build(self) -> int:
        _put(self.sheet, self.row - 1, self.header, [None] * len(self.header))
        for col in range(1, len(self.header) + 1):
            self.sheet.cell(row=self.row - 1, column=col).font = BOLD
        result = self.src.result
        roots = {n["phase_id"]: n for n in self.tree.children.get(None, [])}
        works_rub: list[Decimal | None] = []
        for phase in self.src.payload["phases"]:
            if phase["is_cross_cutting"]:
                continue
            root = roots.get(phase["id"])
            if not phase["enabled"]:
                self._write(1, phase["name"], status="фаза выключена", bold=True)
                continue
            if root is None:
                continue
            self._node(root, 1)
            figures = result.phases.get(phase["id"])
            cost = self._cost(root)
            works_rub.append(cost[1])
            self._write(
                None,
                f"Итого «{phase['name']}»",
                e=figures.e if figures else None,
                sigma=figures.sigma if figures else None,
                cost=(None, cost[1], cost[2]) if self.money else None,
                bold=True,
            )
        self._summary(result, works_rub)
        return self.rows

    def _summary(self, result: calc.ProjectResult, works_rub: list[Decimal | None]) -> None:
        money = self.money
        works = None
        pm_cost: tuple[Decimal | None, Decimal | None, Decimal | None] | None = None
        total = None
        if money:
            known = [x for x in works_rub if x is not None]
            works = sum(known, Decimal(0)) if known else Decimal(0)
            pm_rub = money.cost(result.pm.e, PM_ROW)
            pm_cost = (money.rate(PM_ROW), pm_rub, money.cur(pm_rub))
            total = None if pm_rub is None else works + pm_rub
        project = self.src.project
        figure = project["quote_figure"]
        self._write(
            None,
            "Работы",
            e=result.works.e,
            sigma=result.works.sigma,
            cost=(None, works, money.cur(works)) if money else None,
            bold=True,
        )
        self._write(
            None,
            f"Управление проектом {project['pm_percent']} %",
            e=result.pm.e,
            sigma=result.pm.sigma,
            cost=pm_cost,
            bold=True,
        )
        self._write(
            None,
            "Итог E",
            e=result.total.e,
            sigma=result.total.sigma,
            cost=(None, total, money.cur(total)) if money else None,
            bold=True,
            fill=QUOTE_FILL if figure == "e" else None,
        )
        self._write(
            None, "P80", e=result.total.p80, bold=True, fill=QUOTE_FILL if figure == "p80" else None
        )
        self._write(
            None, "P90", e=result.total.p90, bold=True, fill=QUOTE_FILL if figure == "p90" else None
        )
        quote = {"e": result.total.e, "p80": result.total.p80, "p90": result.total.p90}[figure]
        self._write(None, f"Цифра для КП: {FIGURE_LABEL[figure]}", e=quote, bold=True)


def _assumptions(sheet: Worksheet, src: Source) -> int:
    tree = _Tree(src.payload)
    write_row_bold(sheet, 1, ["Категория", "Метка", "Текст", "Путь узла"])
    row = 2
    for category, label in CATEGORY_LABEL.items():
        for n in src.payload["nodes"]:
            for line in n.get("comment_lines") or []:
                if not isinstance(line, Mapping):
                    continue
                tag = str(line.get("tag_id"))
                if src.categories.get(tag) != category:
                    continue
                values: list[Value] = [
                    label,
                    tree.tags.get(tag, ""),
                    str(line.get("text", "")),
                    " › ".join(tree.path(n["id"])),
                ]
                _put(sheet, row, values, [None] * 4)
                row += 1
    reason = src.project.get("pm_percent_reason")
    if reason:
        _put(
            sheet,
            row,
            ["Обоснование процента УП", None, str(reason), None],
            [None] * 4,
        )
        row += 1
    return row - 2


def write_row_bold(sheet: Worksheet, row: int, values: Sequence[Value]) -> None:
    _put(sheet, row, values, [None] * len(values))
    for col in range(1, len(values) + 1):
        sheet.cell(row=row, column=col).font = BOLD


def parameters(src: Source, mark: marks.Mark) -> list[tuple[str, Value]]:
    project = src.project
    phases = ", ".join(
        p["name"]
        for p in src.payload["phases"]
        if p["in_pm_base"] and p["enabled"] and not p["is_cross_cutting"]
    )
    version = (
        f"Снимок «{src.snapshot_name}»" if src.snapshot_name else f"Версия {src.project_version}"
    )
    return [
        ("Проект", project["name"]),
        ("Заказчик", project.get("customer") or ""),
        ("Уровень детализации", LEVEL_LABEL.get(project["detail_level"], project["detail_level"])),
        ("Процент УП", f"{project['pm_percent']} %"),
        ("Фазы базы УП", phases),
        ("Цифра для КП", FIGURE_LABEL[project["quote_figure"]]),
        ("Дата выгрузки", mark.local_time),
        ("Кто выгрузил", mark.full_name),
        ("Версия проекта или название снимка", version),
    ]


def write_parameters(sheet: Worksheet, items: Sequence[tuple[str, Value]]) -> None:
    write_row_bold(sheet, 1, ["Параметр", "Значение"])
    for i, (name, value) in enumerate(items, start=2):
        _put(sheet, i, [name, value], [None, None])


def estimate_workbook(
    src: Source, mark: marks.Mark, *, money: calc.MoneySettings | None = None
) -> tuple[Workbook, int]:
    """Книга «Часы» (или основа «С деньгами» при ``money``) и число строк дерева."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Оценка"
    rows = _Estimate(sheet, src, _Money(money) if money else None).build()
    sheet.freeze_panes = sheet.cell(row=DATA_ROW + 1, column=3)
    sheet.column_dimensions["B"].width = 48
    _assumptions(book.create_sheet("Допущения и риски"), src)
    return book, rows


def finish(book: Workbook, mark: marks.Mark) -> bytes:
    marks.apply_xlsx(book, mark)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def file_name(src: Source, mark: marks.Mark, kind_part: str) -> str:
    when = src.snapshot_name or today(mark.moment, mark.timezone)
    return marks.file_name(src.project["name"], when, kind_part, "xlsx")


@engine.register("hours_xlsx")
async def build(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    if job.project_id is None:  # pragma: no cover — вид всегда проектный
        raise ValueError("hours_xlsx без проекта")
    src = await load(db, job.project_id, job.snapshot_id, with_money=False)
    book, rows = estimate_workbook(src, mark)
    write_parameters(book.create_sheet("Параметры"), parameters(src, mark))
    return engine.Built(finish(book, mark), file_name(src, mark, "часы"), rows)
