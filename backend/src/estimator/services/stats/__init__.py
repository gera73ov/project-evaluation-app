"""CORE-050/051 · статистика проекта (SPEC 10.1, 11.8 №2–8, 11.9 №1–3, 11.10 №1–5, 11.11,
BR-TREE-09, BR-PRJ-08, FR-REV-03, GAP-08; 15.2 ``GET /projects/{id}/stats``).

* ``readiness`` — сетка «фаза работ × дисциплина»: E ячейки, статус ветки, время последней
  правки (позднее из правки листьев ветки и смены статуса), флажки: ◆ ``large`` (крупный лист),
  ↔ ``wide_fork`` (σ/E > 30%), ? ``open_question`` (открытое обсуждение на узле ветки),
  ``no_expert`` (у дисциплины нет эксперта), ⏰ ``overdue`` (дедлайн прошёл, ветка не готова;
  ``overdue_working_days`` — рабочих дней после дедлайна, BR-PRJ-08, GAP-08).
* ``totals`` — по фазам и дисциплинам E/σ/P80/P90 и доля, «Работы», УП, итог, «Цифра для КП»,
  срок. ``ratios`` — контрольные соотношения справочника (6.6). ``volumes`` — листья по типам с
  ×N. ``candidates`` — топ-10 по E (с пометкой «повторяющийся») и топ-10 по σ/E.
  ``tag_lists`` — строки комментариев с метками категорий «Допущение», «Ограничение», «Риск»,
  «Тех.» с путём узла. ``reviewed`` — доля E с «Проверено» и доля самопроверки по дисциплинам.
  ``dynamics`` — ряд ``project_totals_daily``.
* ``money`` — только с ``money.read`` (G-03): стоимости, цифры для КП, динамика и снимки в валюте.

Обсуждения, вопросы заказчику и список снимков — свои эндпоинты (``/threads``,
``/customer-questions``, ``/snapshots``); в «Снимках» статистики интерфейс берёт их оттуда.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.calendar import working_days
from estimator.api.common.decimal import format_decimal
from estimator.auth.policy import read_settings
from estimator.db.enums import BranchStatusValue, ProjectRole, ThreadStatus
from estimator.db.models.dictionaries import CommentTag, ControlRatio, NodeType
from estimator.db.models.discussions import Thread
from estimator.db.models.projects import Project, ProjectMember
from estimator.domain import calc
from estimator.domain.calc.analytics import Verdict, control_ratio, decomposition, shares, volumes
from estimator.services.common import app_today, hours
from estimator.services.money import stats as money_stats
from estimator.services.money import totals as money_totals
from estimator.services.snapshots import list_snapshots, snapshots_out
from estimator.services.tree.edit import work_type
from estimator.services.tree.load import Computed, _thresholds, compute

_READY = {BranchStatusValue.DONE, BranchStatusValue.NOT_NEEDED}
TAG_CATEGORIES = ("assumption", "constraint", "risk", "tech")
_VERDICT = {Verdict.BELOW: "below", Verdict.WITHIN: "ok", Verdict.ABOVE: "above"}


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(calc.round_half_up(value, 1))


def _share(part: Decimal, whole: Decimal) -> str | None:
    return None if not whole else _pct(part * 100 / whole)


def _hours(f: calc.Figures) -> dict[str, str | None]:
    return {"e": hours(f.e), "sigma": hours(f.sigma), "p80": hours(f.p80), "p90": hours(f.p90)}


def _paths(nodes: list[Any], phases: Mapping[str, str], disciplines: Mapping[str, str]) -> dict:
    by_id = {str(n.id): n for n in nodes}

    def title(n: Any) -> str:
        if n.title:
            return str(n.title)
        if str(n.kind) == "phase":
            return phases.get(str(n.phase_id), "")
        return disciplines.get(str(n.discipline_id), "")

    out: dict[str, list[str]] = {}
    for nid, n in by_id.items():
        path: list[str] = []
        parent = str(n.parent_id) if n.parent_id else None
        while parent and parent in by_id and len(path) < 20:
            path.append(title(by_id[parent]))
            parent = str(by_id[parent].parent_id) if by_id[parent].parent_id else None
        out[nid] = list(reversed(path))
    return out


async def _readiness(
    db: AsyncSession, project: Project, c: Computed, flags: Any
) -> list[dict[str, Any]]:
    result = c.result
    statuses = {(str(b.phase_id), str(b.discipline_id)): b for b, _, _ in c.status_rows}
    experts = set(
        await db.scalars(
            select(ProjectMember.discipline_id).where(
                ProjectMember.project_id == project.id, ProjectMember.role == ProjectRole.EXPERT
            )
        )
    )
    open_nodes = set(
        await db.scalars(
            select(Thread.node_id).where(
                Thread.project_id == project.id,
                Thread.status == ThreadStatus.OPEN,
                Thread.node_id.is_not(None),
            )
        )
    )
    cell_of: dict[str, tuple[str, str]] = {}
    last: dict[tuple[str, str], dt.datetime] = {}
    marks: dict[tuple[str, str], set[str]] = defaultdict(set)
    for n in c.nodes:
        if not n.discipline_id:
            continue
        key = (str(n.phase_id), str(n.discipline_id))
        cell_of[str(n.id)] = key
        if n.updated_at and (key not in last or n.updated_at > last[key]):
            last[key] = n.updated_at
        if n.id in open_nodes:
            marks[key].add("open_question")
    for nid in flags.large:
        if nid in cell_of:
            marks[cell_of[nid]].add("large")
    for nid in flags.wide_forks:
        if nid in cell_of:
            marks[cell_of[nid]].add("wide_fork")
    today = await app_today(db)
    late = 0
    if project.deadline is not None and project.deadline < today:
        late = await working_days(db, project.deadline, today)
    out: list[dict[str, Any]] = []
    for phase_id, cells in result.discipline_by_phase.items():
        for discipline_id, figures in cells.items():
            key = (phase_id, discipline_id)
            row = statuses.get(key)
            status = BranchStatusValue(str(row.status)) if row else BranchStatusValue.NOT_STARTED
            changed = [d for d in (last.get(key), row.changed_at if row else None) if d]
            cell_flags = set(marks[key])
            if uuid.UUID(discipline_id) not in experts:
                cell_flags.add("no_expert")
            overdue = None
            if late > 0 and status not in _READY:
                cell_flags.add("overdue")
                overdue = late
            out.append(
                {
                    "phase_id": phase_id,
                    "discipline_id": discipline_id,
                    "e": hours(figures.e),
                    "status": status.value,
                    "last_change_at": max(changed) if changed else None,
                    "flags": [
                        f
                        for f in ("large", "wide_fork", "open_question", "no_expert", "overdue")
                        if f in cell_flags
                    ],
                    "overdue_working_days": overdue,
                }
            )
    return out


async def _ratios(db: AsyncSession, result: calc.ProjectResult) -> list[dict[str, Any]]:
    rows = await db.scalars(select(ControlRatio).where(ControlRatio.is_active))
    out = []
    for r in rows:
        value = control_ratio(
            result, str(r.discipline_a_id), [str(b) for b in r.disciplines_b], r.min_pct, r.max_pct
        )
        out.append(
            {
                "ratio_id": str(r.id),
                "pct": _pct(value.pct),
                "min_pct": format_decimal(r.min_pct),
                "max_pct": format_decimal(r.max_pct),
                "verdict": None if value.verdict is None else _VERDICT[value.verdict],
            }
        )
    return out


async def _volumes(db: AsyncSession, result: calc.ProjectResult) -> list[dict[str, Any]]:
    counts = volumes(result)
    work = str(await work_type(db))
    merged: dict[str, int] = defaultdict(int)
    for key, count in counts.items():
        try:
            merged[str(uuid.UUID(key))] += count
        except ValueError:  # лист без типа — «Работа» (BR-TREE-08)
            merged[work] += count
    names = dict(
        (await db.execute(select(NodeType.id, NodeType.name).where(
            NodeType.id.in_([uuid.UUID(k) for k in merged])
        ))).all()
    )  # fmt: skip
    items = [
        {"type_id": k, "name": names.get(uuid.UUID(k), ""), "count": v} for k, v in merged.items()
    ]
    return sorted(items, key=lambda i: (-i["count"], i["name"]))


async def _tag_lists(db: AsyncSession, c: Computed, paths: Mapping[str, list[str]]) -> list[dict]:
    rows = (await db.execute(select(CommentTag.id, CommentTag.category))).all()
    category = {str(i): str(cat) for i, cat in rows}
    lists: dict[str, list[dict[str, Any]]] = {k: [] for k in TAG_CATEGORIES}
    for n in c.nodes:
        for line in n.comment_lines or []:
            tag = line.get("tag_id") if isinstance(line, Mapping) else None
            cat = category.get(str(tag)) if tag else None
            if cat in lists:
                lists[cat].append(
                    {"node_id": str(n.id), "tag_id": str(tag), "text": str(line.get("text", "")),
                     "path": [*paths.get(str(n.id), []), n.title]}
                )  # fmt: skip
    return [{"category": k, "items": v} for k, v in lists.items()]


def _reviewed(c: Computed) -> list[dict[str, Any]]:
    total: dict[str, Decimal] = defaultdict(Decimal)
    checked: dict[str, Decimal] = defaultdict(Decimal)
    own: dict[str, Decimal] = defaultdict(Decimal)
    by_id = {str(n.id): n for n in c.nodes}
    for leaf in c.result.tree.leaves():
        node = by_id.get(leaf.node.id)
        if node is None or leaf.excluded or not node.discipline_id:
            continue
        d = str(node.discipline_id)
        total[d] += leaf.totals.e
        if node.reviewed_by:
            checked[d] += leaf.totals.e
            if node.self_review:
                own[d] += leaf.totals.e
    return [
        {
            "discipline_id": d,
            "reviewed_pct": _share(checked[d], total[d]),
            "self_review_pct": _share(own[d], total[d]),
        }
        for d in c.result.disciplines
    ]


async def project_stats(db: AsyncSession, project: Project, *, with_money: bool) -> dict[str, Any]:
    c = await compute(db, project)
    result = c.result
    settings = await read_settings(db, "method.large_leaf_hours")
    flags = decomposition(result, _thresholds(settings.get("method.large_leaf_hours")))
    share = shares(result)
    phases = {str(p.phase_id): p.name for p in c.phases}
    disciplines = {str(d.discipline_id): d.name for d in c.disciplines}
    paths = _paths(c.nodes, phases, disciplines)
    daily = await money_totals.daily(db, project.id)
    out: dict[str, Any] = {
        "project_version": project.version,
        "readiness": await _readiness(db, project, c, flags),
        "totals": {
            "by_phase": [
                {"phase_id": p, "hours": _hours(f), "share_pct": _pct(share.phases.get(p))}
                for p, f in result.phases.items()
            ],
            "by_discipline": [
                {
                    "discipline_id": d,
                    "hours": _hours(f),
                    "share_pct": _pct(share.disciplines.get(d)),
                }
                for d, f in result.disciplines.items()
            ],
            "works": _hours(result.works),
            "pm": _hours(result.pm),
            "total": _hours(result.total),
            "quote_figure": str(project.quote_figure),
            "duration_weeks": project.duration_weeks,
        },
        "ratios": await _ratios(db, result),
        "volumes": await _volumes(db, result),
        "candidates": {
            "large": [
                {
                    "node_id": x.node_id,
                    "e_unit": hours(x.e_unit),
                    "e": hours(x.e),
                    "repeating": x.repeating,
                }
                for x in flags.top_by_e
            ],
            "wide_fork": [
                {"node_id": x.node_id, "ratio_pct": _pct((x.sigma_ratio or 0) * 100)}
                for x in flags.top_by_sigma_ratio
            ],
        },
        "tag_lists": await _tag_lists(db, c, paths),
        "reviewed": _reviewed(c),
        "dynamics": [
            {"date": d.date.isoformat(), "e": hours(d.e), "p80": hours(d.p80)} for d in daily
        ],
    }
    if with_money:
        money = await money_stats.stats_money(db, project, result, daily)
        snaps = await snapshots_out(db, await list_snapshots(db, project.id), with_money=True)
        money["snapshots"] = [
            {"snapshot_id": s["id"], "quote_cur": s["money"]["quote_cur"]} for s in snaps
        ]
        out["money"] = money
    return out
