"""CSV производственного календаря в формате data.gov.ru (Минтруд) для тестов ADM-008.

Строки годов строятся из списков праздников и переносов: в ячейке месяца — нерабочие дни,
``*`` — сокращённый рабочий день, ``+`` — перенесённый выходной. Год 2025 — по постановлению
Правительства РФ о переносе выходных: суббота 1 ноября рабочая (сокращённая).
"""

from __future__ import annotations

import datetime as dt

HEADER = (
    "Год/Месяц,Январь,Февраль,Март,Апрель,Май,Июнь,Июль,Август,Сентябрь,Октябрь,Ноябрь,Декабрь,"
    "Всего рабочих дней,Всего праздничных и выходных дней,"
    "Количество рабочих часов при 40-часовой рабочей неделе"
)
HOLIDAYS_2025 = {dt.date(2025, 1, d) for d in (1, 2, 3, 6, 7, 8)} | {
    dt.date(2025, 5, 1),
    dt.date(2025, 5, 2),
    dt.date(2025, 5, 8),
    dt.date(2025, 5, 9),
    dt.date(2025, 6, 12),
    dt.date(2025, 6, 13),
    dt.date(2025, 11, 3),
    dt.date(2025, 11, 4),
    dt.date(2025, 12, 31),
}
TRANSFERRED_2025 = {dt.date(2025, 5, 2), dt.date(2025, 12, 31)}  # отметка «+»
WORKING_WEEKENDS_2025 = {dt.date(2025, 11, 1)}
SHORT_2025 = {dt.date(2025, 3, 7), dt.date(2025, 4, 30), dt.date(2025, 6, 11), dt.date(2025, 11, 1)}


def year_row(
    year: int,
    holidays: set[dt.date] = frozenset(),  # type: ignore[assignment]
    working_weekends: set[dt.date] = frozenset(),  # type: ignore[assignment]
    short: set[dt.date] = frozenset(),  # type: ignore[assignment]
    transferred: set[dt.date] = frozenset(),  # type: ignore[assignment]
) -> str:
    cells = [str(year)]
    total = 0
    for month in range(1, 13):
        items = []
        day = dt.date(year, month, 1)
        while day.month == month:
            off = (day.weekday() >= 5 and day not in working_weekends) or day in holidays
            if off:
                items.append(f"{day.day}{'+' if day in transferred else ''}")
            else:
                total += 1
                if day in short:
                    items.append(f"{day.day}*")
            day += dt.timedelta(days=1)
        cells.append('"' + ",".join(items) + '"')
    cells += [str(total), str(365 - total), str(total * 8)]
    return ",".join(cells)


def csv_2024_2025() -> bytes:
    rows = [
        HEADER,
        year_row(2024),
        year_row(2025, HOLIDAYS_2025, WORKING_WEEKENDS_2025, SHORT_2025, TRANSFERRED_2025),
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")
