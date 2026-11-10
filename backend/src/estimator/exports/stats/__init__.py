"""EXP-009 · выгрузки вкладок статистики в Excel и «Допущения и риски» в Word (11.9, 11.10 №4,
FR-EXP-06, GAP-02; contracts/exports.yaml ``stats_tab_xlsx``, ``assumptions_docx``).

Вкладка — один файл, таблица повторяет экран. Данные — ``services.stats.project_stats`` и те же
сервисы, что у экранов «Обсуждения», «Вопросы заказчику», «Снимки». Денежные колонки и
лист «Сумма для КП» (вкладка «Итоги») — только если у выгружающего было ``money.read`` с TOTP.
Тексты обсуждений во вкладку «Обсуждения» не входят — только метаданные (exports.yaml).

Word «Допущения и риски» — черновик раздела КП: разделы по категориям меток и обоснование
процента УП, у строки — путь узла мелким шрифтом. Денег в документе нет; доступ — по
``export.money`` (строка 3.3).
"""

from __future__ import annotations

import datetime as dt
import io
import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import CommentTag, ControlRatio, Discipline, Phase
from estimator.db.models.projects import Project
from estimator.exports import engine, marks
from estimator.exports.safe_values import Value, as_text
from estimator.exports.source import Source, load, today
from estimator.exports.xlsx_hours import (
    BRANCH_LABEL,
    CATEGORY_LABEL,
    HOURS,
    MONEY,
    _put,
    _Tree,
    finish,
    write_row_bold,
)
from estimator.exports.xlsx_money import PM_TITLE, quote_sheet
from estimator.services import snapshots
from estimator.services import stats as stats_service
from estimator.services.customer_questions import listing
from estimator.services.discussions import feed

TABS = {
    "readiness": "Сетка готовности",
    "totals": "Итоги",
    "ratios": "Доли и соотношения",
    "volumes": "Объёмы по типам",
    "candidates": "Кандидаты на декомпозицию",
    "tags": "Списки по меткам",
    "discussions": "Обсуждения",
    "customer_questions": "Вопросы заказчику",
    "reviewed": "Проверено",
    "snapshots": "Снимки",
    "dynamics": "Динамика",
}
FLAG = {
    "large": "крупный лист",
    "wide_fork": "широкая вилка",
    "open_question": "открытый вопрос",
    "no_expert": "нет эксперта",
    "overdue": "просрочено",
}
VERDICT = {"below": "ниже нормы", "ok": "в норме", "above": "выше нормы"}
THREAD_STATUS = {"open": "открыт", "resolved": "решён"}
CQ_STATUS = {
    "new": "новый",
    "sent": "отправлен",
    "answered": "отвечен",
    "closed": "решён",
    "withdrawn": "снят",
}
LIMIT = 200

Table = tuple[list[str], list[list[Value]], list[str | None]]


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _when(value: Any, mark: marks.Mark) -> str | None:
    if value is None:
        return None
    moment = (
        value
        if isinstance(value, dt.datetime)
        else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    return marks.Mark(mark.full_name, moment, mark.timezone).local_time


async def _names(db: AsyncSession) -> tuple[dict[str, str], dict[str, str]]:
    phases = {str(i): n for i, n in (await db.execute(select(Phase.id, Phase.name))).all()}
    disciplines = {
        str(i): n for i, n in (await db.execute(select(Discipline.id, Discipline.name))).all()
    }
    return phases, disciplines


class _Ctx:
    def __init__(
        self,
        db: AsyncSession,
        project: Project,
        data: dict[str, Any],
        money: bool,
        mark: marks.Mark,
    ) -> None:
        self.db, self.project, self.data, self.money, self.mark = db, project, data, money, mark
        self.phases: dict[str, str] = {}
        self.disciplines: dict[str, str] = {}
        self.tree: _Tree | None = None

    def path(self, node_id: str | None) -> str:
        if node_id is None or self.tree is None:
            return "Проект"
        return " › ".join(self.tree.path(str(node_id)))


async def _readiness(c: _Ctx) -> Table:
    head = ["Фаза", "Дисциплина", "E", "Статус", "Последняя правка", "Флажки"]
    rows: list[list[Value]] = [
        [
            c.phases.get(r["phase_id"], ""),
            c.disciplines.get(r["discipline_id"], ""),
            _d(r["e"]),
            BRANCH_LABEL.get(r["status"], r["status"]),
            _when(r["last_change_at"], c.mark),
            ", ".join(FLAG.get(f, f) for f in r["flags"]) or None,
        ]
        for r in c.data["readiness"]
    ]
    fmts: list[str | None] = [None, None, HOURS, None, None, None]
    if c.money:
        for r in c.data["money"]["cost_by_phase"]:
            rows.append([f"Стоимость фазы «{c.phases.get(r['phase_id'], '')}», ₽", None,
                         _d(r["cost_rub"]), None, None, None])  # fmt: skip
    return head, rows, fmts


async def _totals(c: _Ctx) -> Table:
    t = c.data["totals"]
    head = ["Строка", "E", "σ", "P80", "P90", "Доля, %"]
    fmts: list[str | None] = [None, HOURS, HOURS, HOURS, HOURS, None]
    cost: dict[str | None, Any] = {}
    if c.money:
        head += ["Стоимость, ₽"]
        fmts += [MONEY]
        cost = {r["discipline_id"]: r["cost_rub"] for r in c.data["money"]["cost_by_discipline"]}
        cost.update({("phase", r["phase_id"]): r["cost_rub"]  # type: ignore[misc]
                     for r in c.data["money"]["cost_by_phase"]})  # fmt: skip

    def line(name: str, h: Mapping[str, Any], share: Any, money: Any) -> list[Value]:
        out: list[Value] = [name, _d(h["e"]), _d(h["sigma"]), _d(h["p80"]), _d(h["p90"]), _d(share)]
        return out + ([_d(money)] if c.money else [])

    rows = [
        line(c.phases.get(r["phase_id"], ""), r["hours"], r["share_pct"],
             cost.get(("phase", r["phase_id"])))  # type: ignore[call-overload]
        for r in t["by_phase"]
    ]  # fmt: skip
    rows += [
        line(c.disciplines.get(r["discipline_id"], ""), r["hours"], r["share_pct"],
             cost.get(r["discipline_id"]))
        for r in t["by_discipline"]
    ]  # fmt: skip
    rows.append(line("Работы", t["works"], None, None))
    rows.append(line(PM_TITLE, t["pm"], None, cost.get(None)))
    rows.append(line("Итог", t["total"], None, None))
    return head, rows, fmts


async def _ratios(c: _Ctx) -> Table:
    found = {
        str(r.id): r for r in await c.db.scalars(select(ControlRatio).where(ControlRatio.is_active))
    }
    head = ["Соотношение", "Норма, %", "Факт, %", "Оценка"]
    rows: list[list[Value]] = []
    for r in c.data["ratios"]:
        ratio = found.get(r["ratio_id"])
        name = ""
        if ratio is not None:
            a = c.disciplines.get(str(ratio.discipline_a_id), "")
            b = " + ".join(c.disciplines.get(str(x), "") for x in ratio.disciplines_b)
            name = f"{a} / {b}"
        rows.append([name, f"{r['min_pct']}–{r['max_pct']}", _d(r["pct"]),
                     VERDICT.get(r["verdict"] or "")])  # fmt: skip
    return head, rows, [None] * 4


async def _volumes(c: _Ctx) -> Table:
    rows: list[list[Value]] = [[v["name"], v["count"]] for v in c.data["volumes"]]
    return ["Тип", "Единиц с учётом ×N"], rows, [None, None]


async def _candidates(c: _Ctx) -> Table:
    head = ["Путь узла", "E на единицу", "E", "σ/E, %", "Пометка"]
    nodes = c.tree.nodes if c.tree else {}
    rows: list[list[Value]] = []
    for x in c.data["candidates"]["large"]:
        note = "крупный, повторяется" if x["repeating"] else "крупный"
        rows.append([c.path(x["node_id"]), _d(x["e_unit"]), _d(x["e"]), None, note])
    for x in c.data["candidates"]["wide_fork"]:
        e = nodes.get(x["node_id"], {}).get("e")
        rows.append([c.path(x["node_id"]), None, _d(e), _d(x["ratio_pct"]), "широкая вилка"])
    return head, rows, [None, HOURS, HOURS, None, None]


async def _tags(c: _Ctx) -> Table:
    names = {
        str(i): n for i, n in (await c.db.execute(select(CommentTag.id, CommentTag.name))).all()
    }
    rows: list[list[Value]] = [
        [CATEGORY_LABEL.get(group["category"], group["category"]), names.get(i["tag_id"], ""),
         i["text"], " › ".join(i["path"])]
        for group in c.data["tag_lists"]
        for i in group["items"]
    ]  # fmt: skip
    return ["Категория", "Метка", "Текст", "Путь узла"], rows, [None] * 4


async def _discussions(c: _Ctx) -> Table:
    rows: list[list[Value]] = []
    after: dict[str, str] | None = None
    threads: list[dict[str, Any]] = []
    while True:
        items, more, after = await feed.list_threads(
            c.db, c.project.id, feed.ThreadFilter(), limit=LIMIT, after=after
        )
        threads += items
        if not more or after is None:
            break
    ids = {
        uuid.UUID(str(a["target_id"]))
        for t in threads
        for a in t["first_message"]["addressees"]
        if a["target_type"] == "user" and a["target_id"]
    }
    users = await feed.user_refs(c.db, ids)

    def label(a: Mapping[str, Any]) -> str:
        kind, target = a["target_type"], a["target_id"]
        if kind == "user":
            ref = users.get(uuid.UUID(str(target)))
            return ref["full_name"] if ref else "?"
        if kind == "discipline":
            return c.disciplines.get(str(target), "?")
        return {"moderators": "модераторы", "customer": "заказчик"}.get(str(kind), str(kind))

    for t in threads:
        first = t["first_message"]
        rows.append([
            c.path(t["node_id"]),
            t["opened_by"]["full_name"],
            ", ".join(label(a) for a in first["addressees"]) or None,
            THREAD_STATUS.get(str(t["status"]), str(t["status"])),
            _when(first["created_at"], c.mark),
            int(t["replies_count"]) + 1,
        ])  # fmt: skip
    return ["Путь узла", "Автор", "Адресаты", "Статус", "Дата", "Сообщений"], rows, [None] * 6


async def _customer_questions(c: _Ctx) -> Table:
    out: list[dict[str, Any]] = []
    after: int | None = None
    while True:
        items, after = await listing.list_questions(
            c.db, c.project.id, status=None, discipline_id=None, limit=LIMIT, after=after
        )
        out += items
        if after is None:
            break
    rows: list[list[Value]] = []
    for i in out:
        t = i["thread"]
        rows.append([
            f"В-{t['customer_question_no']:03d}",
            " › ".join(i["path"]) or "Проект",
            t["first_message"]["body"],
            t["opened_by"]["full_name"],
            _when(t["first_message"]["created_at"], c.mark),
            CQ_STATUS.get(str(t["customer_status"]), str(t["customer_status"])),
            _when(t["answered_at"], c.mark),
        ])  # fmt: skip
    head = ["№", "Раздел", "Вопрос", "Автор", "Дата", "Статус", "Дата ответа"]
    return head, rows, [None] * 7


async def _reviewed(c: _Ctx) -> Table:
    rows: list[list[Value]] = [
        [c.disciplines.get(r["discipline_id"], ""), _d(r["reviewed_pct"]),
         _d(r["self_review_pct"])]
        for r in c.data["reviewed"]
    ]  # fmt: skip
    return ["Дисциплина", "Проверено, % E", "Самопроверка, % E"], rows, [None] * 3


async def _snapshots(c: _Ctx) -> Table:
    snaps = await snapshots.snapshots_out(
        c.db, await snapshots.list_snapshots(c.db, c.project.id), with_money=c.money
    )
    head = ["Название", "Автор", "Дата", "E", "P80"]
    fmts: list[str | None] = [None, None, None, HOURS, HOURS]
    if c.money:
        head.append("«в КП», валюта")
        fmts.append(MONEY)
    head += ["Ошибочный", "Описание"]
    fmts += [None, None]
    rows: list[list[Value]] = []
    for s in snaps:
        row: list[Value] = [s["name"], s["created_by"]["full_name"], _when(s["created_at"], c.mark),
                            _d(s["totals"].get("e")), _d(s["totals"].get("p80"))]  # fmt: skip
        if c.money:
            row.append(_d(s["money"]["quote_cur"]))
        row += ["да" if s["is_invalid"] else None, s["description"] or None]
        rows.append(row)
    return head, rows, fmts


async def _dynamics(c: _Ctx) -> Table:
    head = ["Дата", "E", "P80"]
    fmts: list[str | None] = [None, HOURS, HOURS]
    cur = {}
    if c.money:
        head.append("Итог в валюте")
        fmts.append(MONEY)
        cur = {d["date"]: d["quote_cur"] for d in c.data["money"]["dynamics"]}
    rows: list[list[Value]] = []
    for d in c.data["dynamics"]:
        day = dt.date.fromisoformat(d["date"]).strftime("%d.%m.%Y")
        row: list[Value] = [day, _d(d["e"]), _d(d["p80"])]
        if c.money:
            row.append(_d(cur.get(d["date"])))
        rows.append(row)
    return head, rows, fmts


BUILD: dict[str, Callable[[_Ctx], Any]] = {
    "readiness": _readiness,
    "totals": _totals,
    "ratios": _ratios,
    "volumes": _volumes,
    "candidates": _candidates,
    "tags": _tags,
    "discussions": _discussions,
    "customer_questions": _customer_questions,
    "reviewed": _reviewed,
    "snapshots": _snapshots,
    "dynamics": _dynamics,
}


def _write(sheet: Worksheet, table: Table, start: int) -> int:
    head, rows, fmts = table
    write_row_bold(sheet, start, head)
    for i, row in enumerate(rows, start=start + 1):
        _put(sheet, i, row, fmts)
    for col, letter in enumerate("ABCDEFGH", start=1):
        if col <= len(head):
            sheet.column_dimensions[letter].width = 40 if col == 1 else 16
    return len(rows)


@engine.register("stats_tab_xlsx")
async def build_tab(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    if job.project_id is None:  # pragma: no cover — вид всегда проектный
        raise ValueError("статистика без проекта")
    project = await db.get(Project, job.project_id)
    if project is None:
        raise ValueError("проект удалён")
    tab = str(job.params["tab"])
    data = await stats_service.project_stats(db, project, with_money=job.with_money)
    ctx = _Ctx(db, project, data, job.with_money, mark)
    ctx.phases, ctx.disciplines = await _names(db)
    src: Source = await load(db, project.id, None, with_money=job.with_money)
    ctx.tree = _Tree(src.payload)
    book = Workbook()
    sheet = book.active
    sheet.title = TABS[tab][:31]
    rows = _write(sheet, await BUILD[tab](ctx), marks.XLSX_DATA_ROW)
    if tab == "totals" and job.with_money and src.money is not None:
        quote_sheet(book.create_sheet("Сумма для КП"), src, src.money)
    when = today(mark.moment, mark.timezone)
    name = marks.file_name(project.name, when, f"статистика-{TABS[tab].lower()}", "xlsx")
    return engine.Built(finish(book, mark), name, rows)


def assumptions_docx(src: Source, mark: marks.Mark) -> tuple[bytes, int]:
    tree = _Tree(src.payload)
    document = Document()
    document.add_heading(f"Допущения и риски — {as_text(src.project['name'])}", level=1)
    count = 0
    for category, title in CATEGORY_LABEL.items():
        items = [
            (n["id"], line)
            for n in src.payload["nodes"]
            for line in n.get("comment_lines") or []
            if isinstance(line, Mapping) and src.categories.get(str(line.get("tag_id"))) == category
        ]
        document.add_heading(title, level=2)
        if not items:
            document.add_paragraph("—")
        for node_id, line in items:
            document.add_paragraph(as_text(line.get("text", "")), style="List Bullet")
            path = document.add_paragraph()
            run = path.add_run(" › ".join(tree.path(node_id)))
            run.font.size = Pt(8)
            count += 1
    document.add_heading("Обоснование процента управления проектом", level=2)
    reason = src.project.get("pm_percent_reason")
    document.add_paragraph(f"Управление проектом — {src.project['pm_percent']} %.")
    if reason:
        document.add_paragraph(as_text(reason))
    marks.apply_docx(document, mark)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue(), count


@engine.register("assumptions_docx")
async def build_assumptions(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    if job.project_id is None:  # pragma: no cover — вид всегда проектный
        raise ValueError("допущения без проекта")
    src = await load(db, job.project_id, None, with_money=False)
    content, rows = assumptions_docx(src, mark)
    name = marks.file_name(
        src.project["name"], today(mark.moment, mark.timezone), "допущения", "docx"
    )
    return engine.Built(content, name, rows)
