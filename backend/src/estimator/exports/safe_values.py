"""EXP-002 · безопасная запись значений в выгрузки (FR-EXP-04, SEC-WEB-06, TC-SEC-05).

* :func:`escape_text` — текст, начинающийся с ``=``, ``+``, ``-``, ``@``, табуляции или возврата
  каретки, получает префикс ``'``: Excel и LibreOffice не примут его за формулу (CSV/формульная
  инъекция, ``=HYPERLINK(...)``).
* :func:`write_row` — запись строки в лист openpyxl только значениями: строки всегда записываются
  как текст (тип ячейки ``s``), формула не может появиться даже из экранированного значения.
* :func:`csv_bytes` — CSV для Excel: UTF-8 с BOM, разделитель ``;``, RFC 4180, первая строка —
  комментарий-отметка (:mod:`estimator.exports.marks`), текст экранируется так же.

Числа (``Decimal``, ``int``, ``float``) пишутся числами: формат и округление при выводе задаёт
вид выгрузки (contracts/exports.yaml, common.values).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet

#: Начала текста, которые табличные редакторы считают формулой
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
CSV_DELIMITER = ";"

Value = str | int | float | Decimal | bool | date | datetime | None


def escape_text(value: str) -> str:
    """``"=HYPERLINK(...)"`` → ``"'=HYPERLINK(...)"``; прочий текст не меняется."""
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def safe_value(value: Value) -> Value:
    """Значение для ячейки: текст экранируется, остальное — как есть."""
    if isinstance(value, str):
        return escape_text(value)
    if value is None or isinstance(value, int | float | Decimal | bool | date | datetime):
        return value
    raise TypeError(f"значение типа {type(value).__name__} не пишется в выгрузку")


def write_cell(cell: Cell, value: Value) -> Cell:
    """Записать значение в ячейку; строка — всегда текст, не формула."""
    safe = safe_value(value)
    cell.value = safe
    if isinstance(safe, str):
        cell.data_type = "s"
    return cell


def write_row(
    sheet: Worksheet, row: int, values: Sequence[Value], *, start_column: int = 1
) -> None:
    """Записать строку значений начиная с ``start_column``."""
    for offset, value in enumerate(values):
        write_cell(sheet.cell(row=row, column=start_column + offset), value)


def _csv_text(value: Value) -> str:
    safe = safe_value(value)
    if safe is None:
        return ""
    if isinstance(safe, bool):
        return "да" if safe else "нет"
    if isinstance(safe, Decimal):
        return format(safe, "f").replace(".", ",")
    if isinstance(safe, float):
        return repr(safe).replace(".", ",")
    if isinstance(safe, datetime):
        return safe.strftime("%d.%m.%Y %H:%M")
    if isinstance(safe, date):
        return safe.strftime("%d.%m.%Y")
    return str(safe)


def csv_bytes(comment: str, header: Sequence[str], rows: Iterable[Sequence[Value]]) -> bytes:
    """CSV: BOM, строка-комментарий, заголовок, строки (числа — с запятой, RFC 4180)."""
    buffer = io.StringIO(newline="")
    buffer.write(comment.replace("\r", " ").replace("\n", " ") + "\r\n")
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow([_csv_text(h) for h in header])
    for row in rows:
        writer.writerow([_csv_text(v) for v in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def as_text(value: Any) -> str:
    """Пользовательский текст для Word: строка как есть (python-docx не разбирает разметку)."""
    return "" if value is None else str(value)
