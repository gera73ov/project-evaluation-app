"""ADM-008 · рабочие дни по производственному календарю (SPEC 7.5, BR-PRJ-08, Q-43).

Чистые функции без ввода-вывода: календарь передаётся словарём «дата → рабочий ли день» за
загруженные годы. Год, для которого календаря нет, считается по правилу Пн–Пт (Q-43).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Mapping

_DAY = dt.timedelta(days=1)


def is_weekend(day: dt.date) -> bool:
    return day.weekday() >= 5


def is_working(
    day: dt.date, calendar: Mapping[dt.date, bool], loaded_years: Collection[int]
) -> bool:
    """Рабочий ли день: по календарю года, если он загружен, иначе Пн–Пт."""
    if day.year in loaded_years:
        return calendar.get(day, not is_weekend(day))
    return not is_weekend(day)


def working_days_between(
    start: dt.date,
    end: dt.date,
    calendar: Mapping[dt.date, bool],
    loaded_years: Collection[int],
) -> int:
    """Рабочих дней в полуинтервале ``(start, end]``: «сколько рабочих дней осталось до дедлайна».

    ``end`` раньше ``start`` — отрицательное число (дедлайн прошёл). Для одной и той же даты — 0.
    """
    if end < start:
        return -working_days_between(end, start, calendar, loaded_years)
    count = 0
    day = start + _DAY
    while day <= end:
        if is_working(day, calendar, loaded_years):
            count += 1
        day += _DAY
    return count


def year_days(year: int, calendar: Mapping[dt.date, bool]) -> list[tuple[dt.date, bool]]:
    """Все дни года с признаком «рабочий» (для ``CalendarYear`` и предпросмотра)."""
    loaded = {year}
    day = dt.date(year, 1, 1)
    out: list[tuple[dt.date, bool]] = []
    while day.year == year:
        out.append((day, is_working(day, calendar, loaded)))
        day += _DAY
    return out


def month_preview(year: int, calendar: Mapping[dt.date, bool]) -> list[dict[str, object]]:
    """Предпросмотр по месяцам (``CalendarPreview.months``): рабочие дни, нерабочие будни,
    рабочие выходные (переносы)."""
    months: dict[int, dict[str, object]] = {
        m: {"month": m, "working_days": 0, "non_working": [], "working_weekends": []}
        for m in range(1, 13)
    }
    for day, working in year_days(year, calendar):
        month = months[day.month]
        if working:
            month["working_days"] = int(month["working_days"]) + 1  # type: ignore[call-overload]
            if is_weekend(day):
                month["working_weekends"].append(day.isoformat())  # type: ignore[attr-defined]
        else:
            month["non_working"].append(day.isoformat())  # type: ignore[attr-defined]
    return list(months.values())
