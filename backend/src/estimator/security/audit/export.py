"""Выгрузка журнала аудита в CSV (SEC-015; SEC-AUD-06, FR-EXP-06, contracts/exports.yaml
``audit_csv``).

Построитель движка выгрузок (EXP-003): ставит ``POST /system/audit/export`` (право
``audit.export``, step-up), файл строится в worker. Формат — :func:`estimator.exports.safe_values
.csv_bytes`: UTF-8 с BOM, «;», RFC 4180, формульные префиксы экранируются, первая строка —
``# Коммерческая тайна; <ФИО>; <дата и время>``. Колонки — запись журнала (SEC-AUD-02) и категория
из каталога; ``details`` — JSON одной строкой. Записи — по возрастанию ``id``.

Выгрузка пишет ``audit.exported`` (фильтры и число строк) в той же транзакции, что и готовый файл.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.audit import AuditLog
from estimator.exports import engine
from estimator.exports.marks import Mark, clean_part
from estimator.exports.safe_values import csv_bytes
from estimator.exports.source import today
from estimator.security import audit
from estimator.security.audit.view import AuditFilter, category, query

KIND = "audit_csv"
COLUMNS = [
    "time", "type", "category", "result", "user_id", "login", "ip", "user_agent", "session_hash",
    "object_type", "object_id", "details", "prev_hash", "hash",
]  # fmt: skip
BATCH = 2000


def _hex(value: bytes | None) -> str | None:
    return bytes(value).hex() if value is not None else None


def row_values(row: AuditLog) -> list[Any]:
    return [
        row.ts.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        row.event_type,
        category(row.event_type),
        str(getattr(row.result, "value", row.result)),
        str(row.user_id) if row.user_id else None,
        row.login,
        str(row.ip) if row.ip is not None else None,
        row.user_agent,
        _hex(row.session_hash),
        row.object_type,
        row.object_id,
        json.dumps(row.details or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        _hex(row.prev_hash),
        _hex(row.hash),
    ]


async def rows(db: AsyncSession, filt: AuditFilter) -> list[list[Any]]:
    out: list[list[Any]] = []
    after = 0
    while True:
        batch = (await db.scalars(query(filt, after=after, limit=BATCH, ascending=True))).all()
        out += [row_values(r) for r in batch]
        if len(batch) < BATCH:
            return out
        after = batch[-1].id


def _period(value: dt.datetime | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "…"


def file_name(mark: Mark, filt: AuditFilter) -> str:
    """``Аудит_<ДД.ММ.ГГГГ>_<с>-<по>.csv`` (дата выгрузки — в поясе выгружающего)."""
    made = today(mark.moment, mark.timezone).strftime("%d.%m.%Y")
    period = f"{_period(filt.since)}-{_period(filt.until)}"
    return f"{clean_part(f'Аудит_{made}_{period}')}.csv"


@engine.register(KIND)
async def build(db: AsyncSession, job: engine.Job, mark: Mark) -> engine.Built:
    filt = AuditFilter.from_params(job.params)
    data = await rows(db, filt)
    from estimator.db.models.users import User

    user = await db.get(User, job.user_id)
    await audit.write(
        db, "audit.exported", user_id=job.user_id, login=user.login if user else None,
        object_type="audit_log", details={"filters": filt.summary(), "rows": len(data)},
    )  # fmt: skip
    return engine.Built(
        csv_bytes(mark.csv_comment, COLUMNS, data), file_name(mark, filt), len(data)
    )
