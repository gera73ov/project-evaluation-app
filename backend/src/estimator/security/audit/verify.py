"""Проверка хэш-цепочки журнала аудита (SEC-004; SEC-AUD-03, DEC-20261105-db-audit-hash-chain).

Для каждой записи по возрастанию ``id``:

1. ``hash`` совпадает с ``audit.row_hash(запись)`` — запись не изменена;
2. ``prev_hash`` равен ``hash`` предыдущей записи (у первой — якорю ``audit_anchor`` после
   ``audit purge`` или 32 нулевым байтам) — записи не удалены и не вставлены в середину.

Проверка идёт пачками по ``id`` и не держит блокировку: записи, добавленные во время проверки,
проверяются, если попали в выборку. Результат — :class:`VerifyResult`; запись события
``system.audit_chain.verified`` и индикатор «Состояния системы» делает :func:`run_and_record`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

ZERO_HASH = bytes(32)
BATCH = 5000
#: Ключ Redis с результатом последней проверки (индикатор «Состояния системы», 18.4).
LAST_RESULT_KEY = "audit:verify:last"

_ANCHOR = text("SELECT last_purged_hash FROM audit.audit_anchor WHERE id = 1")
_BATCH = text(
    "SELECT l.id, l.prev_hash, l.hash, audit.row_hash(l) = l.hash AS intact "
    "FROM audit.audit_log AS l WHERE l.id > :after ORDER BY l.id LIMIT :limit"
)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_broken_id: str | None = None
    reason: str | None = None  # modified | chain — для вывода команды, в аудит не пишется
    finished_at: str = ""

    def details(self) -> dict[str, object]:
        """``details`` события ``system.audit_chain.verified``."""
        return {"ok": self.ok, "checked": self.checked, "first_broken_id": self.first_broken_id}


async def verify_chain(conn: AsyncConnection | AsyncSession, *, batch: int = BATCH) -> VerifyResult:
    anchor = (await conn.execute(_ANCHOR)).scalar_one_or_none()
    expected = bytes(anchor) if anchor is not None else ZERO_HASH
    checked = 0
    after = 0
    now = datetime.now(UTC).isoformat()
    while True:
        rows = (await conn.execute(_BATCH, {"after": after, "limit": batch})).all()
        if not rows:
            return VerifyResult(ok=True, checked=checked, finished_at=now)
        for row_id, prev_hash, row_hash, intact in rows:
            if bytes(prev_hash) != expected:
                return VerifyResult(False, checked, str(row_id), "chain", now)
            if not intact:
                return VerifyResult(False, checked, str(row_id), "modified", now)
            expected = bytes(row_hash)
            checked += 1
            after = row_id


def result_json(result: VerifyResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False)
