"""ADM-008 · производственный календарь (SPEC 7.5, BR-PRJ-08, Q-43, GAP-03, SEC-WEB-08;
15.2 ``CRUD /admin/calendar``).

* :func:`working_days_between` — утилита «рабочих дней между датами» для дедлайнов «Моих оценок»
  (BR-PRJ-08) и статистики; год без календаря считается по Пн–Пт (Q-43).
* Загрузка CSV data.gov.ru с предпросмотром по месяцам (:mod:`.csvfile`), точечные правки года,
  удаление года. Каждое изменение — событие аудита ``dict.changed`` «было → стало».
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.calendar.workdays import (
    is_working,
    month_preview,
    working_days_between,
    year_days,
)
from estimator.db.models.dictionaries import WorkCalendarDay
from estimator.security import audit

__all__ = [
    "delete_year",
    "list_years",
    "load_calendar",
    "month_preview",
    "replace_year",
    "working_days",
    "working_days_between",
    "year_body",
]


async def load_calendar(
    db: AsyncSession, years: Iterable[int]
) -> tuple[dict[dt.date, bool], set[int]]:
    """Дни календаря за ``years`` и множество годов, для которых календарь загружен."""
    wanted = sorted(set(years))
    rows = (
        await db.execute(
            select(WorkCalendarDay.date, WorkCalendarDay.is_working).where(
                WorkCalendarDay.year.in_(wanted)
            )
        )
    ).all()
    calendar = dict(rows)
    return calendar, {d.year for d in calendar}


async def working_days(db: AsyncSession, start: dt.date, end: dt.date) -> int:
    """Рабочих дней в ``(start, end]`` по календарю БД (BR-PRJ-08)."""
    low, high = min(start, end), max(start, end)
    calendar, loaded = await load_calendar(db, range(low.year, high.year + 1))
    return working_days_between(start, end, calendar, loaded)


def year_body(year: int, calendar: Mapping[dt.date, bool]) -> dict[str, Any]:
    """Тело ``CalendarYear``: все дни года."""
    return {
        "year": year,
        "days": [{"date": d.isoformat(), "is_working": w} for d, w in year_days(year, calendar)],
    }


async def list_years(db: AsyncSession, year: int | None = None) -> list[dict[str, Any]]:
    stmt = select(WorkCalendarDay.year).distinct().order_by(WorkCalendarDay.year)
    if year is not None:
        stmt = stmt.where(WorkCalendarDay.year == year)
    years = list((await db.scalars(stmt)).all())
    calendar, _ = await load_calendar(db, years)
    return [year_body(y, calendar) for y in years]


def _diff(
    old: Mapping[dt.date, bool], new: Mapping[dt.date, bool], year: int
) -> dict[str, list[Any]]:
    """«Было → стало» по дням, где признак изменился (пустой старый год — Пн–Пт)."""
    loaded_old = {year} if old else set()
    changes: dict[str, list[Any]] = {}
    for day, working in sorted(new.items()):
        before = is_working(day, old, loaded_old)
        if before != working:
            changes[day.isoformat()] = [before, working]
    return changes


async def replace_year(
    db: AsyncSession,
    year: int,
    days: Mapping[dt.date, bool],
    *,
    actor: Any,
    op: str,
) -> dict[str, Any]:
    """Заменить календарь года: ``days`` — признаки дней (отсутствующие дни — по Пн–Пт)."""
    old, _ = await load_calendar(db, [year])
    full = {d: days.get(d, w) for d, w in year_days(year, {})}
    rows = [
        {
            "date": d,
            "is_working": w,
            "year": year,
            "created_by": actor.user_id,
            "updated_by": actor.user_id,
        }
        for d, w in full.items()
    ]
    stmt = insert(WorkCalendarDay).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkCalendarDay.date],
        set_={
            "is_working": stmt.excluded.is_working,
            "updated_by": stmt.excluded.updated_by,
            "updated_at": dt.datetime.now(dt.UTC),
        },
    )
    await db.execute(stmt)
    await _audit(db, actor, year, op, _diff(old, full, year))
    return year_body(year, full)


async def delete_year(db: AsyncSession, year: int, *, actor: Any) -> bool:
    old, _ = await load_calendar(db, [year])
    if not old:
        return False
    await db.execute(delete(WorkCalendarDay).where(WorkCalendarDay.year == year))
    weekdays = {d: not w for d, w in ((d, d.weekday() >= 5) for d in old)}
    await _audit(db, actor, year, "delete", _diff(old, weekdays, year))
    return True


async def _audit(
    db: AsyncSession, actor: Any, year: int, op: str, changes: dict[str, list[Any]]
) -> None:
    await audit.write(
        db,
        "dict.changed",
        user_id=actor.user_id,
        login=actor.login,
        session_id=actor.session_id,
        object_type="dictionary_item",
        object_id=f"calendar:{year}",
        details={"dictionary": "calendar", "op": op, "changes": changes},
    )
