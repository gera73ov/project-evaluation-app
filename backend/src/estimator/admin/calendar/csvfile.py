"""ADM-008 · разбор CSV производственного календаря data.gov.ru (Минтруд) без правок (GAP-03).

Формат набора открытых данных «Производственный календарь»: строка заголовка, затем строка на
год. Первый столбец — год, следующие 12 — месяцы; в ячейке месяца через запятую перечислены
**нерабочие** дни (выходные и праздники). Отметки у числа:

* ``*`` — сокращённый предпраздничный день: день рабочий (в список нерабочих не входит);
* ``+`` — перенесённый выходной: день нерабочий.

Суббота или воскресенье, которых нет в списке, — рабочий день (перенос). Остальные столбцы
(итоги, часы) не читаются. Кодировка — UTF-8 (с BOM или без) или Windows-1251. Если в файле
несколько лет, загружается самый поздний (обычно это календарь будущего года).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass

MAX_BYTES = 256 * 1024  # SEC-WEB-08
YEAR_MIN, YEAR_MAX = 2000, 2100
_DAY_RE = re.compile(r"^(\d{1,2})([*+]?)$")


class CalendarFileError(ValueError):
    """Файл не в формате data.gov.ru; ``field`` — где ошибка (для VALIDATION_FAILED)."""

    def __init__(self, message: str, field: str = "/file") -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class ParsedYear:
    year: int
    non_working: frozenset[dt.date]

    def calendar(self) -> dict[dt.date, bool]:
        """Все дни года: рабочий, если его нет в списке нерабочих."""
        out: dict[dt.date, bool] = {}
        day = dt.date(self.year, 1, 1)
        while day.year == self.year:
            out[day] = day not in self.non_working
            day += dt.timedelta(days=1)
        return out


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CalendarFileError("Файл не в кодировке UTF-8 или Windows-1251")  # pragma: no cover


def _year_row(row: list[str], line: int) -> ParsedYear | None:
    if not row or not row[0].strip().isdigit():
        return None
    year = int(row[0].strip())
    if not YEAR_MIN <= year <= YEAR_MAX:
        raise CalendarFileError(f"Строка {line}: год {year} вне диапазона {YEAR_MIN}–{YEAR_MAX}")
    if len(row) < 13:
        raise CalendarFileError(f"Строка {line}: нет 12 столбцов месяцев")
    days: set[dt.date] = set()
    for month in range(1, 13):
        cell = row[month].strip()
        for item in filter(None, (part.strip() for part in cell.split(","))):
            match = _DAY_RE.match(item)
            if match is None:
                raise CalendarFileError(f"Строка {line}, месяц {month}: «{item}» — не число дня")
            try:
                day = dt.date(year, month, int(match.group(1)))
            except ValueError:
                raise CalendarFileError(
                    f"Строка {line}, месяц {month}: дня {match.group(1)} нет в месяце"
                ) from None
            if match.group(2) != "*":
                days.add(day)
    return ParsedYear(year, frozenset(days))


def parse(raw: bytes) -> ParsedYear:
    """Год календаря из файла (самый поздний, если лет несколько)."""
    if len(raw) > MAX_BYTES:
        raise CalendarFileError("Файл больше 256 КБ")
    text = _decode(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    years: list[ParsedYear] = []
    for line, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
        parsed = _year_row(row, line)
        if parsed is not None:
            years.append(parsed)
    if not years:
        raise CalendarFileError("В файле нет строк с годом: ожидается формат data.gov.ru")
    return max(years, key=lambda y: y.year)
