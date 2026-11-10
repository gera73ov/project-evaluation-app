"""``estimator audit purge`` — удаление записей аудита старше срока хранения (SEC-016; SEC-AUD-04).

Срок — настройка суперадминистратора ``retention.periods.audit_months`` (по умолчанию 12, не меньше
6 месяцев, Q-38, NFR-REL-06). Граница — начало суток UTC ``сегодня − срок``.

Удаление идёт от роли БД ``estimator_audit_purge`` под той же блокировкой цепочки, что берёт
``audit.append`` (``AUDIT_LOCK_KEY``): удаляются записи с ``id`` не больше последней записи старше
границы, а её ``hash`` сохраняется якорем ``audit.audit_anchor``. Первая оставшаяся запись ссылается
``prev_hash`` на этот хэш, поэтому ``audit verify`` после purge проходит (SEC-AUD-03).

Результат — событие ``system.audit.purged`` от роли приложения (у роли purge нет права на
``audit.append``); оно же уходит в SIEM обычной передачей журнала (SEC-012).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from estimator.config import Settings, get_settings
from estimator.db import roles
from estimator.db.models.audit import AUDIT_LOCK_KEY
from estimator.security import audit

MIN_MONTHS = 6

_LAST = text("SELECT id, hash FROM audit.audit_log WHERE ts < :before ORDER BY id DESC LIMIT 1")
_COUNT = text("SELECT count(*) FROM audit.audit_log WHERE id <= :last")
_DELETE = text("DELETE FROM audit.audit_log WHERE id <= :last")
_ANCHOR = text(
    "INSERT INTO audit.audit_anchor "
    "(id, last_purged_id, last_purged_hash, purged_until, purged_at) "
    "VALUES (1, :id, :hash, :before, now()) "
    "ON CONFLICT (id) DO UPDATE SET last_purged_id = EXCLUDED.last_purged_id, "
    "last_purged_hash = EXCLUDED.last_purged_hash, purged_until = EXCLUDED.purged_until, "
    "purged_at = EXCLUDED.purged_at"
)
_TOUCH = text("UPDATE audit.audit_anchor SET purged_at = now() WHERE id = 1")
_MONTHS = text(
    "SELECT value -> 'audit_months' FROM system_settings WHERE key = 'retention.periods'"
)


class PurgeError(Exception):
    """Недопустимый срок хранения: команда ничего не удаляет."""


@dataclass(frozen=True)
class PurgeResult:
    before: dt.date
    months: int
    deleted: int
    anchor_hash: str | None
    dry_run: bool = False

    def details(self) -> dict[str, object]:
        """``details`` события ``system.audit.purged`` (contracts/audit-events.yaml)."""
        return {
            "before": self.before.isoformat(),
            "deleted": self.deleted,
            "anchor_hash": self.anchor_hash or "",
        }


def boundary(today: dt.date, months: int) -> dt.date:
    """``today`` минус ``months`` календарных месяцев (31-е → последний день месяца)."""
    if months < MIN_MONTHS:
        raise PurgeError(f"срок хранения аудита {months} мес. меньше минимума {MIN_MONTHS} мес.")
    total = today.year * 12 + today.month - 1 - months
    year, month = divmod(total, 12)
    month += 1
    for day in (today.day, 30, 29, 28):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("недостижимо")  # pragma: no cover


async def retention_months(conn: AsyncConnection) -> int:
    from estimator.admin.settings import schema

    raw = (await conn.execute(_MONTHS)).scalar_one_or_none()
    return int(schema.default("retention.periods")["audit_months"] if raw is None else raw)


async def purge_before(
    conn: AsyncConnection, start: dt.datetime, *, dry_run: bool = False
) -> tuple[int, str | None]:
    """Удалить записи с ``ts < start`` в транзакции ``conn`` (роль purge). → (удалено, якорь)."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
    last = (await conn.execute(_LAST, {"before": start})).first()
    if last is None:
        if not dry_run:
            await conn.execute(_TOUCH)
        return 0, None
    last_id, last_hash = int(last[0]), bytes(last[1])
    if dry_run:
        return int((await conn.execute(_COUNT, {"last": last_id})).scalar_one()), last_hash.hex()
    deleted = (await conn.execute(_DELETE, {"last": last_id})).rowcount
    await conn.execute(_ANCHOR, {"id": last_id, "hash": last_hash, "before": start})
    return int(deleted or 0), last_hash.hex()


async def run(
    settings: Settings | None = None,
    *,
    today: dt.date | None = None,
    dry_run: bool = False,
    os_user: str | None = None,
) -> PurgeResult:
    """Команда целиком: срок из настроек, удаление, событие в аудит."""
    from estimator.db.session import create_engine

    settings = settings or get_settings()
    app = create_engine(settings)
    purger = create_engine(settings, role=roles.AUDIT_PURGE)
    try:
        async with app.connect() as conn:
            months = await retention_months(conn)
        before = boundary(today or dt.datetime.now(dt.UTC).date(), months)
        async with purger.begin() as conn:
            start = dt.datetime.combine(before, dt.time(), tzinfo=dt.UTC)
            deleted, anchor = await purge_before(conn, start, dry_run=dry_run)
        result = PurgeResult(before, months, deleted, anchor, dry_run)
        if not dry_run:
            await audit.write_standalone(
                "system.audit.purged", "success",
                sessionmaker=async_sessionmaker(app, expire_on_commit=False),
                object_type="audit_log", details=result.details(), actor="cli", os_user=os_user,
            )  # fmt: skip
        return result
    finally:
        await purger.dispose()
        await app.dispose()
