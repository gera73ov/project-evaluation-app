"""EXP-010 · Excel «Портфель» (FR-PORT-01, FR-PORT-02, 11.13 №1; contracts/exports.yaml
``portfolio_xlsx``; 15.2 ``POST /portfolio/export``).

Листы «Реестр» (все проекты периода по дате создания, как ``GET /portfolio/projects``),
«Сводка» (как ``GET /portfolio/summary``) и «Параметры». Суммы сводки — в ₽ без НДС, как на
экране. Фильтры, кроме периода, в контракте выгрузки не передаются: в «Параметрах» — «все».
Выгрузка целиком денежная: право ``portfolio.export`` у руководителя пресейла (TOTP — gate).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.exports import engine, marks
from estimator.exports.safe_values import Value
from estimator.exports.source import today
from estimator.exports.xlsx_hours import (
    FIGURE_LABEL,
    HOURS,
    MONEY,
    _put,
    finish,
    write_parameters,
    write_row_bold,
)
from estimator.services import portfolio

STATUS = {
    "preparation": "Подготовка",
    "estimation": "Оценка",
    "consolidation": "Сведение",
    "completed": "Завершена",
    "archived": "Архив",
}
OUTCOME = {
    "unknown": "не известен",
    "won": "выигран",
    "lost": "проигран",
    "cancelled": "отменён заказчиком",
}
REGISTRY = [
    "Проект",
    "Заказчик",
    "Модераторы",
    "Пресейл",
    "Статус",
    "«Цифра для КП»",
    "«в КП», ч",
    "«в КП», валюта",
    "Валюта",
    "Итог без НДС, ₽",
    "Результат",
    "Сумма договора",
    "Дата изменения",
]
PAGE = 200


def _d(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _names(people: list[dict[str, Any]]) -> str:
    return ", ".join(p["full_name"] for p in people)


async def registry(db: AsyncSession, date_from: dt.date, date_to: dt.date) -> list[dict[str, Any]]:
    flt = portfolio.PortfolioFilter(date_from=date_from, date_to=date_to)
    out: list[dict[str, Any]] = []
    after: list[str] | None = None
    while True:
        items, after = await portfolio.projects(db, flt, after=after, limit=PAGE)
        out += items
        if after is None:
            return out


def workbook(items: list[dict[str, Any]], summary: dict[str, Any], mark: marks.Mark) -> Workbook:
    book = Workbook()
    sheet = book.active
    sheet.title = "Реестр"
    start = marks.XLSX_DATA_ROW
    write_row_bold(sheet, start, REGISTRY)
    fmts: list[str | None] = [None] * 6 + [HOURS, MONEY, None, MONEY, None, MONEY, None]
    for row, p in enumerate(items, start=start + 1):
        m = p["money"]
        updated = p["updated_at"]
        values: list[Value] = [
            p["name"],
            p["customer"] or "",
            _names(p["moderators"]),
            _names(p["presales"]),
            STATUS.get(p["status"], p["status"]),
            FIGURE_LABEL.get(p["quote_figure"], p["quote_figure"]),
            _d(p["quote_hours"]),
            _d(m["quote_cur"]),
            m["currency"],
            _d(m["quote_rub"]),
            OUTCOME.get(p["outcome"], p["outcome"]),
            _d(m["contract_amount"]),
            marks.Mark(mark.full_name, updated, mark.timezone).local_time if updated else None,
        ]
        _put(sheet, row, values, fmts)
    sheet.column_dimensions["A"].width = 40

    totals = book.create_sheet("Сводка")
    write_row_bold(totals, 1, ["Показатель", "Значение"])
    lines: list[tuple[str, Value, str | None]] = []
    for key, count in summary["by_status"].items():
        lines.append((f"Проектов: {STATUS.get(key, key)}", count, None))
    for key, count in summary["by_outcome"].items():
        lines.append((f"Результат: {OUTCOME.get(key, key)}", count, None))
    lines += [
        ("Сумма оценок выигранных, ₽ без НДС", _d(summary["sum_won_cur"]), MONEY),
        ("Сумма оценок проигранных, ₽ без НДС", _d(summary["sum_lost_cur"]), MONEY),
        ("Сумма «в КП» проектов в работе, ₽ без НДС", _d(summary["sum_in_progress_cur"]), MONEY),
        ("Доля выигранных по числу, %", _d(summary["won_share_count_pct"]), None),
        ("Доля выигранных по деньгам, %", _d(summary["won_share_money_pct"]), None),
        ("Медиана «договор / в КП», %", _d(summary["contract_to_quote_median_pct"]), None),
        (
            "Медиана «создание проекта → первый снимок», дней",
            _d(summary["first_snapshot_median_days"]),
            None,
        ),
    ]
    for reason in summary["loss_reasons"]:
        lines.append((f"Причина проигрыша: {reason['name']}", reason["count"], None))
        lines += [(" · другое", text, None) for text in reason["texts"]]
    for i, (name, value, fmt) in enumerate(lines, start=2):
        _put(totals, i, [name, value], [None, fmt])
    totals.column_dimensions["A"].width = 50
    return book


@engine.register("portfolio_xlsx")
async def build(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    date_from = dt.date.fromisoformat(str(job.params["from"]))
    date_to = dt.date.fromisoformat(str(job.params["to"]))
    items = await registry(db, date_from, date_to)
    summary = await portfolio.summary(db, date_from, date_to)
    book = workbook(items, summary, mark)
    period = f"{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}"
    write_parameters(
        book.create_sheet("Параметры"),
        [
            ("Период (по дате создания)", period),
            ("Статус", "все"),
            ("Результат", "все"),
            ("Модератор", "все"),
            ("Поиск", ""),
            ("Дата выгрузки", mark.local_time),
            ("Кто выгрузил", mark.full_name),
        ],
    )
    name = marks.file_name("Портфель", today(mark.moment, mark.timezone), "портфель", "xlsx")
    return engine.Built(finish(book, mark), name, len(items))
