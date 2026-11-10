"""EXP-005 · Excel «С деньгами» и лист «Для КП» (FR-EXP-02, BR-MONEY-04…06, R-01, BR-PRJ-06,
TC-MONEY-01, G-18; contracts/exports.yaml ``money_xlsx``).

Книга — как «Часы» (:func:`estimator.exports.xlsx_hours.estimate_workbook`) с колонками денег на
«Оценке», плюс лист «Для КП»: строки дисциплин и УП по «Цифре для КП» (``округл(стоимость
строки по E без округления · K_F)``, :mod:`estimator.domain.calc.money`) в ₽ и в валюте, «Итог
без НДС», «НДС N %», «Итого с НДС», «Цифра для КП» в часах, «Срок, недель» и блок сравнения
E / P80 / P90. Суммы столбцов равны итогам: итоги — суммы округлённых строк (6.4).

Ставки не заданы — на «Для КП» строка «не заданы ставки: …» вместо сумм (BR-MONEY-02).
Вид целиком денежный: ставит его только держатель ``export.money`` с TOTP (gate).
"""

from __future__ import annotations

from decimal import Decimal

from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.domain import calc
from estimator.domain.calc._decimal import round_half_up
from estimator.domain.calc.model import PM_ROW
from estimator.exports import engine, marks
from estimator.exports.safe_values import Value
from estimator.exports.source import Source, load
from estimator.exports.xlsx_hours import (
    BOLD,
    FIGURE_LABEL,
    HOURS,
    MONEY,
    QUOTE_FILL,
    _put,
    estimate_workbook,
    file_name,
    finish,
    parameters,
    write_parameters,
    write_row_bold,
)

PM_TITLE = "Управление проектом"


def _figure_hours(result: calc.ProjectResult, figure: calc.QuoteFigure) -> Decimal:
    t = result.total
    return {calc.QuoteFigure.E: t.e, calc.QuoteFigure.P80: t.p80, calc.QuoteFigure.P90: t.p90}[
        figure
    ]


def quote_sheet(sheet: Worksheet, src: Source, money: calc.MoneySettings) -> int:
    result = src.result
    computed = calc.calculate_money(result, money)
    cur = money.currency
    figure = computed.quote_figure
    label = FIGURE_LABEL[str(figure)]
    write_row_bold(sheet, 1, ["Строка", "По E, ₽", f"Для КП ({label}), ₽", f"Для КП, {cur}"])
    if computed.by_figure is None:
        _put(sheet, 2, [computed.rates_missing_text, None, None, None], [None] * 4)
        return 0
    by_e, quote = computed.by_figure[calc.QuoteFigure.E], computed.by_figure[figure]
    fmts = [None, MONEY, MONEY, MONEY]
    row = 2
    names = [(d.id, d.name) for d in result.input.disciplines] + [(PM_ROW, PM_TITLE)]
    for key, name in names:
        values: list[Value] = [name, by_e.rows_rub[key], quote.rows_rub[key], quote.rows_cur[key]]
        _put(sheet, row, values, fmts)
        row += 1
    _put(sheet, row, ["Итог без НДС", by_e.total_rub, quote.total_rub, quote.total_cur], fmts)
    row += 1
    _put(sheet, row, [computed.vat_label, by_e.vat_rub, quote.vat_rub, quote.vat_cur], fmts)
    row += 1
    totals: list[Value] = [
        "Итого с НДС",
        by_e.total_with_vat_rub,
        quote.total_with_vat_rub,
        quote.total_with_vat_cur,
    ]
    _put(sheet, row, totals, fmts)
    for col in range(1, 5):
        sheet.cell(row=row, column=col).font = BOLD
    row += 2
    hours = round_half_up(_figure_hours(result, figure), 1)
    _put(sheet, row, [f"Цифра для КП ({label}), ч", hours], [None, HOURS])
    row += 1
    weeks = src.project.get("duration_weeks")
    _put(sheet, row, ["Срок, недель", weeks], [None, None])
    row += 2
    head = ["", "Часы", "Без НДС, ₽", "НДС, ₽", "С НДС, ₽", f"Без НДС, {cur}", f"С НДС, {cur}"]
    write_row_bold(sheet, row, head)
    row += 1
    for fig in calc.QuoteFigure:
        m = computed.by_figure[fig]
        line: list[Value] = [
            FIGURE_LABEL[str(fig)],
            round_half_up(_figure_hours(result, fig), 1),
            m.total_rub,
            m.vat_rub,
            m.total_with_vat_rub,
            m.total_cur,
            m.total_with_vat_cur,
        ]
        _put(sheet, row, line, [None, HOURS, MONEY, MONEY, MONEY, MONEY, MONEY])
        if fig is figure:
            for col in range(1, 8):
                sheet.cell(row=row, column=col).fill = QUOTE_FILL
        row += 1
    return len(names)


def money_parameters(src: Source, money: calc.MoneySettings) -> list[tuple[str, Value]]:
    vat = "не облагается" if money.vat_percent is None else f"{money.vat_percent:f} %"
    return [
        ("Валюта КП", money.currency),
        ("Курс (₽ за единицу)", money.exchange_rate),
        ("Ставка НДС", vat),
        ("Срок недель", src.project.get("duration_weeks")),
    ]


@engine.register("money_xlsx")
async def build(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    if job.project_id is None or not job.with_money:  # pragma: no cover — проверено при постановке
        raise ValueError("money_xlsx без проекта или без права на деньги")
    src = await load(db, job.project_id, job.snapshot_id, with_money=True)
    if src.money is None:
        raise ValueError("у проекта нет настроек денег")
    book, rows = estimate_workbook(src, mark, money=src.money)
    quote_sheet(book.create_sheet("Для КП", 1), src, src.money)
    params = parameters(src, mark) + money_parameters(src, src.money)
    write_parameters(book.create_sheet("Параметры"), params)
    return engine.Built(finish(book, mark), file_name(src, mark, "деньги"), rows)
