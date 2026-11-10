"""Просмотр журнала аудита (SEC-015; SEC-AUD-06, Q-27, ``GET /system/audit``).

Суперадминистратор и аудитор ИБ видят все события. Администратор — только категории
«Справочники» и «Пользователи и роли» (``audit.read.admin_categories``, фильтр
``admin_audit_categories``). Категории в таблице нет: она следует из типа события по каталогу,
поэтому ограничение — список типов этих категорий. Событие неизвестного каталогу типа
администратору не показывается.

Порядок — от новых к старым по ``id`` (записи фиксируются строго по ``id``, см. ``audit.append``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.audit import AuditLog
from estimator.security.audit.catalog import EVENTS

ADMIN_CATEGORIES = frozenset({"dictionaries", "users_roles"})
ADMIN_SCOPE = "admin_audit_categories"


def category(event_type: str) -> str:
    spec = EVENTS.get(event_type)
    return spec.category if spec else event_type.split(".", 1)[0]


def types_of(categories: Collection[str]) -> list[str]:
    return sorted(name for name, spec in EVENTS.items() if spec.category in categories)


@dataclass(frozen=True)
class AuditFilter:
    since: dt.datetime | None = None
    until: dt.datetime | None = None
    user_id: uuid.UUID | None = None
    event_type: str | None = None
    result: str | None = None
    #: None — все категории; иначе только перечисленные (администратор).
    categories: frozenset[str] | None = field(default=None)

    def to_params(self) -> dict[str, Any]:
        """Параметры задачи выгрузки (JSON)."""
        return {
            "from": _iso(self.since), "to": _iso(self.until),
            "user_id": str(self.user_id) if self.user_id else None,
            "event_type": self.event_type, "result": self.result,
            "categories": sorted(self.categories) if self.categories is not None else None,
        }  # fmt: skip

    @classmethod
    def from_params(cls, raw: dict[str, Any]) -> AuditFilter:
        def ts(key: str) -> dt.datetime | None:
            return dt.datetime.fromisoformat(raw[key]) if raw.get(key) else None

        cats = raw.get("categories")
        return cls(
            since=ts("from"), until=ts("to"),
            user_id=uuid.UUID(raw["user_id"]) if raw.get("user_id") else None,
            event_type=raw.get("event_type"), result=raw.get("result"),
            categories=frozenset(cats) if cats is not None else None,
        )  # fmt: skip

    def summary(self) -> dict[str, Any]:
        """Фильтры для ``audit.viewed`` / ``audit.exported`` (details.filters)."""
        out: dict[str, Any] = {}
        if self.since or self.until:
            out["period"] = [_iso(self.since), _iso(self.until)]
        if self.user_id:
            out["user_id"] = str(self.user_id)
        if self.event_type:
            out["type"] = self.event_type
        if self.result:
            out["result"] = self.result
        if self.categories is not None:
            out["category"] = sorted(self.categories)
        return out


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def query(
    filt: AuditFilter, *, before: int | None = None, after: int | None = None,
    limit: int | None = None, ascending: bool = False,
) -> Any:  # fmt: skip
    """Выборка записей по фильтру: от новых к старым (просмотр) или по возрастанию (выгрузка)."""
    q = select(AuditLog).order_by(AuditLog.id.asc() if ascending else AuditLog.id.desc())
    if filt.since is not None:
        q = q.where(AuditLog.ts >= filt.since)
    if filt.until is not None:
        q = q.where(AuditLog.ts < filt.until)
    if filt.user_id is not None:
        q = q.where(AuditLog.user_id == filt.user_id)
    if filt.event_type:
        q = q.where(AuditLog.event_type == filt.event_type)
    if filt.result:
        q = q.where(AuditLog.result == filt.result)
    if filt.categories is not None:
        q = q.where(AuditLog.event_type.in_(types_of(filt.categories)))
    if before is not None:
        q = q.where(AuditLog.id < before)
    if after is not None:
        q = q.where(AuditLog.id > after)
    if limit is not None:
        q = q.limit(limit)
    return q


def entry(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": row.ts,
        "event_type": row.event_type,
        "category": category(row.event_type),
        "result": str(row.result.value if hasattr(row.result, "value") else row.result),
        "user_id": row.user_id,
        "login": row.login,
        "ip": str(row.ip) if row.ip is not None else None,
        "user_agent": row.user_agent,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "details": row.details or {},
    }


async def list_entries(
    db: AsyncSession, filt: AuditFilter, *, before: int | None, limit: int
) -> list[dict[str, Any]]:
    """До ``limit + 1`` записей с ``id < before`` (лишняя — признак следующей страницы)."""
    rows = (await db.scalars(query(filt, before=before, limit=limit + 1))).all()
    return [entry(r) for r in rows]
