"""Общие помощники сервисов CORE: часы для вывода, ссылка на пользователя, «сегодня» по поясу
приложения, версия проекта и ``change_log`` (SPEC 15.1, 15.3, ARCH-02, FR-UI-02)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import read_settings
from estimator.config import get_settings
from estimator.db.models.tree import ChangeLog
from estimator.domain.calc import round_half_up
from estimator.realtime.bus import publish

_BUMP = text("UPDATE projects SET version = version + 1 WHERE id = :id RETURNING version")


def hours(value: Decimal | None) -> str | None:
    """Расчётные часы для API: 2 знака, ROUND_HALF_UP (``HoursString``, api-conventions 2.1)."""
    if value is None:
        return None
    return format(round_half_up(value, 2), "f")


def initials(full_name: str) -> str:
    """Инициалы для аватара: первые буквы двух первых слов (``Анна Смирнова`` → ``АС``)."""
    letters = [part[0] for part in full_name.split() if part][:2]
    return "".join(letters).upper() or "?"


def user_ref(
    user_id: uuid.UUID, full_name: str, *, is_active: bool | None = None
) -> dict[str, Any]:
    """``UserRef`` контрактов openapi.yaml и ws-events.schema.json."""
    ref: dict[str, Any] = {
        "id": str(user_id),
        "full_name": full_name,
        "initials": initials(full_name),
    }
    if is_active is not None:
        ref["is_active"] = is_active
    return ref


async def app_timezone(db: AsyncSession) -> ZoneInfo:
    """Часовой пояс приложения: ``app.timezone`` из system_settings, иначе ``APP_TIMEZONE``."""
    value = (await read_settings(db, "app.timezone")).get("app.timezone")
    for name in (value, get_settings().app_timezone, "UTC"):
        if isinstance(name, str) and name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return ZoneInfo("UTC")  # pragma: no cover — UTC есть всегда


async def app_today(db: AsyncSession, now: dt.datetime | None = None) -> dt.date:
    """Сегодняшняя дата по часовому поясу приложения (дедлайн «не раньше сегодня», FR-PRJ-01)."""
    moment = now or dt.datetime.now(dt.UTC)
    return moment.astimezone(await app_timezone(db)).date()


async def bump_version(db: AsyncSession, project_id: uuid.UUID) -> int:
    """``projects.version++`` атомарно (одной командой UPDATE … RETURNING), новая версия.

    Новая версия — повод пересчитать кэш итогов проекта (CORE-026, ARCH-03).
    """
    from estimator.services.projects.totals import schedule

    version = int((await db.execute(_BUMP, {"id": project_id})).scalar_one())
    schedule(db, project_id)
    return version


def log_change(
    db: AsyncSession, project_id: uuid.UUID, version: int, event: Mapping[str, Any]
) -> None:
    """Запись ``change_log`` для догона после переподключения (ARCH-02); событие без денег."""
    db.add(ChangeLog(project_id=project_id, version=version, event=dict(event)))


async def emit(db: AsyncSession, project_id: uuid.UUID, event: str, data: Mapping[str, Any]) -> int:
    """Событие проекта со своей версией: ``version++``, публикация после commit, ``change_log``.

    Одна версия — одно событие (ключ ``change_log`` — проект и версия, ARCH-02).
    """
    version = await bump_version(db, project_id)
    message = publish(db, f"project:{project_id}", event, data, project_version=version)
    log_change(db, project_id, version, message)
    return version
