"""EXP-008 · Excel «Сравнение со снимком» (FR-SNAP-03…05, 11.12 №5; contracts/exports.yaml
``snapshot_diff_xlsx``).

Таблица — то же сравнение, что ``GET /snapshots/{id}/diff``
(:func:`estimator.services.snapshots.diff.compare`): лист «Сводка» (итог E, P80; с деньгами —
«в КП» в ₽ и в валюте и вклад курса) и лист «Изменения» (узлы и параметры проекта). Денежные
строки и колонки — только если у выгружающего было ``money.read`` с TOTP; без него их нет.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.files import Snapshot
from estimator.db.models.projects import Project
from estimator.exports import engine, marks
from estimator.exports.safe_values import Value
from estimator.exports.xlsx_hours import HOURS, MONEY, _put, finish, write_row_bold
from estimator.services import snapshots
from estimator.services.money import snapshot as snapshot_money
from estimator.services.snapshots import diff

CURRENT = "current"
CURRENT_LABEL = "Текущее состояние"
CHANGE = {
    "added": "добавлен",
    "removed": "удалён",
    "changed": "изменён",
    "moved": "перемещён",
}
FIELD = {
    "title": "название",
    "o": "O",
    "r": "R",
    "p": "P",
    "multiplier": "×N",
    "type": "тип",
    "comment": "комментарий",
    "parent": "родитель",
    "position": "порядок",
    "phase": "фаза",
    "discipline": "дисциплина",
}


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _estimate(raw: Mapping[str, Any] | None) -> str | None:
    if raw is None:
        return None
    e = raw["e"]
    if raw["o"] is None:
        return f"E {e}"
    return f"{raw['o']}–{raw['r']}–{raw['p']} ×{raw['multiplier']} → E {e}"


async def _side(db: AsyncSession, snap: Snapshot, money: bool) -> diff.Side:
    raw = (await snapshot_money.stored_payloads(db, [snap.id])).get(snap.id) if money else None
    return diff.Side(str(snap.id), snap.name, snap.payload, raw)


async def sides(
    db: AsyncSession, base_id: uuid.UUID, other: str, money: bool
) -> tuple[Project, diff.Side, diff.Side]:
    base = await db.get(Snapshot, base_id)
    if base is None:
        raise ValueError("снимок удалён")
    project = await db.get(Project, base.project_id)
    if project is None:  # pragma: no cover — снимок держит проект
        raise ValueError("проект удалён")
    if other == CURRENT:
        raw = await snapshot_money.current_payload(db, project.id) if money else None
        right = diff.Side(None, CURRENT_LABEL, await snapshots.capture(db, project), raw)
    else:
        found = await db.get(Snapshot, uuid.UUID(other))
        if found is None or found.project_id != project.id:
            raise ValueError("снимок сравнения удалён")
        right = await _side(db, found, money)
    return project, await _side(db, base, money), right


def workbook(result: Mapping[str, Any], *, money: bool) -> tuple[Workbook, int]:
    book = Workbook()
    summary = book.active
    summary.title = "Сводка"
    start = marks.XLSX_DATA_ROW
    left, right = result["base"], result["with"]
    write_row_bold(summary, start, ["Показатель", left["label"], right["label"], "Разница"])
    row = start + 1
    for key, label in (("e", "Итог E"), ("p80", "P80")):
        before, after = _dec(left["totals"][key]), _dec(right["totals"][key])
        values: list[Value] = [label, before, after, _dec(result["totals_delta"][key])]
        _put(summary, row, values, [None, HOURS, HOURS, HOURS])
        row += 1
    block = result.get("money") if money else None
    if block:
        b, w = block["base"], block["with"]
        lines: list[tuple[str, Any, Any, Any]] = [
            ("«в КП», ₽", b["total_rub"], w["total_rub"], block["total_delta_rub"]),
            (f"«в КП», {w['currency']}", b["total_cur"], w["total_cur"], block["total_delta_cur"]),
            ("Вклад изменения курса", None, None, block["exchange_effect_cur"]),
        ]
        for label, before, after, delta in lines:
            _put(
                summary, row, [label, _dec(before), _dec(after), _dec(delta)], [None] + [MONEY] * 3
            )
            row += 1

    changes = book.create_sheet("Изменения")
    head = ["Вид изменения", "Путь узла", "Узел", "Поле", "Было", "Стало", "ΔE"]
    if block:
        head += ["Δ, ₽"]
    head += ["Автор последнего изменения"]
    write_row_bold(changes, 1, head)
    deltas = {r["node_id"]: r["delta_cost_rub"] for r in (block or {}).get("rows", [])}
    row = 2
    count = 0
    for r in result["rows"]:
        values = [
            CHANGE.get(r["change"], r["change"]),
            " › ".join(r["path"]),
            r["title"],
            ", ".join(FIELD.get(f, f) for f in r["fields"]) or None,
            _estimate(r["before"]),
            _estimate(r["after"]),
            _dec(r["delta_e"]),
        ]
        formats: list[str | None] = [None, None, None, None, None, None, HOURS]
        if block:
            values.append(_dec(deltas.get(r["node_id"])))
            formats.append(MONEY)
        author = r.get("last_changed_by")
        values.append(author["full_name"] if author else None)
        formats.append(None)
        _put(changes, row, values, formats)
        row += 1
        count += 1
    pm = result.get("pm")
    if pm:
        before, after = f"{pm['percent_before']} %", f"{pm['percent_after']} %"
        values = ["параметр проекта", None, "Управление проектом", "% УП", before, after]
        values.append(_dec(pm["delta_e"]))
        formats = [None] * 6 + [HOURS]
        if block:
            values.append(_dec(deltas.get(None)))
            formats.append(MONEY)
        values.append(None)
        formats.append(None)
        _put(changes, row, values, formats)
        row += 1
    for p in result["params"]:
        if p["is_money"] and not block:  # pragma: no cover — compare без денег их не отдаёт
            continue
        values = ["параметр проекта", None, None, p["label"], p["before"], p["after"], None]
        values += [None] if block else []
        values.append(None)
        _put(changes, row, values, [None] * len(values))
        row += 1
    return book, count


@engine.register("snapshot_diff_xlsx")
async def build(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    if job.snapshot_id is None:  # pragma: no cover — проверено при постановке
        raise ValueError("сравнение без снимка")
    other = str(job.params.get("with", CURRENT))
    project, left, right = await sides(db, job.snapshot_id, other, job.with_money)
    result = diff.compare(left, right, with_money=job.with_money)
    book, rows = workbook(result, money=job.with_money)
    when = f"{left.label} — {right.label}"
    name = marks.file_name(project.name, when, "сравнение", "xlsx")
    return engine.Built(finish(book, mark), name, rows)
