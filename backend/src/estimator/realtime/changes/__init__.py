"""RT-007 · догрузка изменений после разрыва (FR-TREE-33, ARCH-02, NFR-REL-06, TC-CONC-03).

``change_log`` хранит события проекта по версиям (пишет ядро, ``services.common.emit``), без
денег. Клиент после переподключения просит всё, что новее его ``since``:

* ``GET /projects/{id}/changes?since=`` — ответ ``{from_version, to_version, events}`` или
  410 ``VERSION_TOO_OLD`` с ``current_version``;
* ``subscribe {since}`` по WebSocket — те же события сразу после ``ack``, либо ``resync: true``
  и ``resync.required``.

События проходят тот же фильтр по правам подписчика, что и живые (:func:`hub.allowed`).
Пропуски номеров нормальны (деньги и заметки в журнал не пишутся). «Слишком старая» версия —
та, что предшествует удалённым записям: ночная очистка (:func:`purge`) удаляет записи старше
``retention.change_log_days`` (7 дней), но оставляет по проекту последнюю из старых — она
отмечает границу хранения. Сильное отставание (больше :data:`MAX_EVENTS`) — тоже полная
перезагрузка.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import read_settings
from estimator.db.models.tree import ChangeLog

DEFAULT_RETENTION_DAYS = 7
MAX_EVENTS = 1000

Event = dict[str, Any]


class VersionTooOld(Exception):
    """Нужна полная перезагрузка дерева."""

    def __init__(self, current_version: int) -> None:
        super().__init__("VERSION_TOO_OLD")
        self.current_version = current_version


@dataclass(frozen=True)
class Changes:
    from_version: int
    to_version: int
    events: list[Event]

    def body(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "events": self.events,
        }


async def retention_days(db: AsyncSession) -> int:
    value = (await read_settings(db, "retention")).get("retention") or {}
    try:
        return int(value.get("change_log_days", DEFAULT_RETENTION_DAYS))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_RETENTION_DAYS


async def changes_since(
    db: AsyncSession,
    project_id: uuid.UUID,
    since: int,
    current_version: int,
    *,
    allowed: Callable[[Event], bool] = lambda _e: True,
    now: dt.datetime | None = None,
) -> Changes:
    """События с версией > ``since`` по правам; иначе :class:`VersionTooOld`."""
    if since > current_version:
        raise VersionTooOld(current_version)
    if since == current_version:
        return Changes(since, current_version, [])
    floor = (
        await db.execute(
            select(ChangeLog.version, ChangeLog.created_at)
            .where(ChangeLog.project_id == project_id)
            .order_by(ChangeLog.version)
            .limit(1)
        )
    ).first()
    if floor is not None and since < floor[0] - 1:
        cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=await retention_days(db))
        if floor[1] < cutoff:  # раньше границы записи уже удалены
            raise VersionTooOld(current_version)
    rows = (
        await db.scalars(
            select(ChangeLog.event)
            .where(ChangeLog.project_id == project_id, ChangeLog.version > since)
            .order_by(ChangeLog.version)
            .limit(MAX_EVENTS + 1)
        )
    ).all()
    if len(rows) > MAX_EVENTS:
        raise VersionTooOld(current_version)
    return Changes(since, current_version, [dict(e) for e in rows if allowed(dict(e))])


_PURGE = text(
    """
    DELETE FROM change_log c
    USING (
        SELECT project_id, max(version) AS keep
        FROM change_log WHERE created_at < :cutoff GROUP BY project_id
    ) k
    WHERE c.project_id = k.project_id AND c.created_at < :cutoff AND c.version < k.keep
    """
)


async def purge(db: AsyncSession, *, now: dt.datetime | None = None) -> int:
    """Удалить записи старше срока хранения (кроме границы по каждому проекту)."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=await retention_days(db))
    result = await db.execute(_PURGE, {"cutoff": cutoff})
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
