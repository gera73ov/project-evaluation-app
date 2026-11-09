"""ADM-008: утилита рабочих дней (Q-43) и разбор CSV data.gov.ru (GAP-03)."""

from __future__ import annotations

import datetime as dt

import pytest

from estimator.admin.calendar.csvfile import CalendarFileError, parse
from estimator.admin.calendar.workdays import month_preview, working_days_between
from tests.support.calendar_csv import HEADER, csv_2024_2025, year_row

pytestmark = [pytest.mark.spec("BR-PRJ-08"), pytest.mark.spec("Q-43")]

D = dt.date


def test_without_calendar_is_mon_fri() -> None:
    # пятница → следующая пятница: 5 рабочих дней
    assert working_days_between(D(2026, 11, 6), D(2026, 11, 13), {}, set()) == 5
    assert working_days_between(D(2026, 11, 6), D(2026, 11, 6), {}, set()) == 0
    assert working_days_between(D(2026, 11, 13), D(2026, 11, 6), {}, set()) == -5
    assert working_days_between(D(2026, 11, 6), D(2026, 11, 8), {}, set()) == 0  # выходные


@pytest.mark.spec("7.5")
def test_with_transfers() -> None:
    year = parse(csv_2024_2025())
    calendar = year.calendar()
    loaded = {2025}
    # 31.10 (пт) → 05.11 (ср): 01.11 (сб) рабочая, 03–04.11 праздники, 05.11 рабочий
    assert working_days_between(D(2025, 10, 31), D(2025, 11, 5), calendar, loaded) == 2
    # новогодние каникулы: с 31.12.2024 по 09.01.2025 рабочий только 9 января
    assert working_days_between(D(2024, 12, 31), D(2025, 1, 9), calendar, loaded) == 1
    # через границу года: 2024 без календаря — по Пн–Пт
    assert working_days_between(D(2024, 12, 27), D(2024, 12, 31), calendar, loaded) == 2


def test_parse_takes_latest_year_and_marks() -> None:
    year = parse(csv_2024_2025())
    assert year.year == 2025
    assert D(2025, 3, 7) not in year.non_working  # «7*» — сокращённый рабочий
    assert D(2025, 5, 2) in year.non_working  # «2+» — перенесённый выходной
    assert D(2025, 11, 1) not in year.non_working
    months = month_preview(2025, year.calendar())
    assert months[10]["working_weekends"] == ["2025-11-01"]
    assert sum(m["working_days"] for m in months) == 261 - 15 + 1


def test_parse_cp1251() -> None:
    raw = (HEADER + "\n" + year_row(2026) + "\n").encode("cp1251")
    assert parse(raw).year == 2026


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "нет строк"),
        (b"just,text\n", "нет строк"),
        (b"1999," + b",".join([b'""'] * 12) + b"\n", "вне диапазона"),
        (b'2025,"1,2"\n', "нет 12"),
        (b'2025,"1,x"' + b',""' * 11 + b"\n", "не число"),
        (b'2025,"1","30"' + b',""' * 10 + b"\n", "нет в месяце"),
        (b"x" * (256 * 1024 + 1), "256"),
    ],
)
def test_parse_errors(raw: bytes, message: str) -> None:
    with pytest.raises(CalendarFileError, match=message):
        parse(raw)
