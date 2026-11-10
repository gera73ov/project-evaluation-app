"""CORE-070 · портфель руководителя пресейла (SPEC FR-PORT-01, FR-PORT-02, 10.4, 11.13 №1–6, R-02,
Q-31, GAP-05; 15.2 ``GET /portfolio/projects``, ``GET /portfolio/summary``).

* Реестр — все проекты, в том числе «Архив»: модераторы и пресейл, статус, «в КП» в часах с
  меткой цифры, в валюте КП и в ₽ без НДС, стоимость по E, результат, договор, дата изменения
  (как в «Моих оценках» — последняя правка проекта или дерева), «без модератора», «не заданы
  ставки». Фильтры: период по дате создания (по часовому поясу приложения), статус, результат,
  модератор, поиск по названию и заказчику. Порядок — от новых к старым; курсор — дата создания и
  id последней строки.
* Сводка за период (по дате создания): число по статусам и результатам; доля выигранных из
  проектов с известным итогом (выигран + проигран) по числу и по деньгам; суммы «в КП» выигранных,
  проигранных и проектов в работе («Подготовка», «Оценка», «Сведение»); причины проигрыша с
  текстами «Другое»; медиана «договор / в КП» по выигранным (договор и «в КП» — в валюте КП);
  результаты по месяцам создания; справочная медиана «создание → первый снимок» в днях (GAP-05).
* Суммы сводки — в ₽ без НДС (``quote_rub``): у проектов разные валюты КП, и складывать их можно
  только в рублях (11.13 №6 «в рублях без НДС — для сравнения разных валют»). Проценты — один знак.
* Деньги отдаются без проверки членства: ``portfolio.read`` — право руководителя пресейла с
  деньгами во всех проектах (R-02), TOTP проверяет gate. Первое открытие чужого проекта за сессию
  пишет в аудит авторизатор (``project.opened_by_presale_head``, R-PRESALE-HEAD).
"""

from __future__ import annotations

import datetime as dt
import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.db.enums import ProjectOutcome, ProjectRole, ProjectStatus, UserStatus
from estimator.db.models.dictionaries import LossReason
from estimator.db.models.files import Snapshot
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.tree import ChangeLog
from estimator.db.models.users import User
from estimator.domain.calc import round_half_up
from estimator.services.common import app_timezone, hours, user_ref
from estimator.services.money.totals import PortfolioMoney, cached, portfolio_money

IN_PROGRESS = (ProjectStatus.PREPARATION, ProjectStatus.ESTIMATION, ProjectStatus.CONSOLIDATION)
NO_REASON = "Причина не указана"


@dataclass(frozen=True)
class PortfolioFilter:
    status: ProjectStatus | None = None
    outcome: ProjectOutcome | None = None
    moderator_id: uuid.UUID | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    q: str | None = None


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _pct(part: Decimal | int, whole: Decimal | int) -> str | None:
    if not whole:
        return None
    return format_decimal(round_half_up(Decimal(part) * 100 / Decimal(whole), 1))


async def _period(
    db: AsyncSession, date_from: dt.date | None, date_to: dt.date | None
) -> list[Any]:
    """Условия «дата создания по поясу приложения в [from; to]»."""
    zone = await app_timezone(db)
    conds: list[Any] = []
    if date_from is not None:
        conds.append(Project.created_at >= dt.datetime.combine(date_from, dt.time(), zone))
    if date_to is not None:
        end = dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time(), zone)
        conds.append(Project.created_at < end)
    return conds


async def _conditions(db: AsyncSession, flt: PortfolioFilter) -> list[Any]:
    conds = await _period(db, flt.date_from, flt.date_to)
    if flt.status is not None:
        conds.append(Project.status == flt.status)
    if flt.outcome is not None:
        conds.append(Project.outcome == flt.outcome)
    if flt.moderator_id is not None:
        conds.append(
            exists().where(
                ProjectMember.project_id == Project.id,
                ProjectMember.role == ProjectRole.MODERATOR,
                ProjectMember.user_id == flt.moderator_id,
            )
        )
    if flt.q and flt.q.strip():
        pattern = _like(flt.q.strip())
        conds.append(or_(Project.name.ilike(pattern), Project.customer.ilike(pattern)))
    return conds


async def _people(
    db: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> dict[tuple[uuid.UUID, ProjectRole], list[dict[str, Any]]]:
    rows = await db.execute(
        select(ProjectMember.project_id, ProjectMember.role, User.id, User.full_name, User.status)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.role.in_((ProjectRole.MODERATOR, ProjectRole.PRESALE)),
        )
        .distinct()
        .order_by(User.full_name, User.id)
    )
    out: dict[tuple[uuid.UUID, ProjectRole], list[dict[str, Any]]] = defaultdict(list)
    for pid, role, uid, name, status in rows.all():
        out[(pid, ProjectRole(role))].append(
            user_ref(uid, name, is_active=status is UserStatus.ACTIVE)
        )
    return out


async def _changed_at(db: AsyncSession, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
    rows = await db.execute(
        select(ChangeLog.project_id, func.max(ChangeLog.created_at))
        .where(ChangeLog.project_id.in_(project_ids))
        .group_by(ChangeLog.project_id)
    )
    return dict(rows.all())


def _money_out(m: PortfolioMoney | None) -> dict[str, Any]:
    if m is None:  # pragma: no cover — строка project_money создаётся вместе с проектом
        return {"currency": "RUB", "quote_cur": None, "quote_rub": None, "cost_rub": None,
                "contract_amount": None, "rates_missing": False}  # fmt: skip
    return {
        "currency": m.currency,
        "quote_cur": _money(m.quote_cur),
        "quote_rub": _money(m.quote_rub),
        "cost_rub": _money(m.cost_rub),
        "contract_amount": _money(m.contract_amount),
        "rates_missing": m.rates_missing,
    }


async def projects(
    db: AsyncSession, flt: PortfolioFilter, *, after: list[str] | None, limit: int
) -> tuple[list[dict[str, Any]], list[str] | None]:
    """Страница реестра и ключ последней строки, если есть следующая страница."""
    stmt = select(Project).where(*await _conditions(db, flt))
    if after is not None:
        stmt = stmt.where(
            tuple_(Project.created_at, Project.id)
            < tuple_(dt.datetime.fromisoformat(after[0]), uuid.UUID(after[1]))
        )
    found = list(
        await db.scalars(
            stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)
        )
    )
    page, more = found[:limit], len(found) > limit
    ids = [p.id for p in page]
    if not ids:
        return [], None
    totals = await cached(db, ids, ())
    money = await portfolio_money(db, ids)
    people = await _people(db, ids)
    changed = await _changed_at(db, ids)
    items: list[dict[str, Any]] = []
    for p in page:
        row = totals.get(p.id)
        figure = str(p.quote_figure)
        quote = None
        if row is not None and row.e:
            quote = hours({"e": row.e, "p80": row.p80, "p90": row.p90}[figure])
        updated = max(d for d in (p.updated_at, changed.get(p.id)) if d is not None)
        items.append(
            {
                "id": str(p.id),
                "name": p.name,
                "customer": p.customer,
                "moderators": people.get((p.id, ProjectRole.MODERATOR), []),
                "presales": people.get((p.id, ProjectRole.PRESALE), []),
                "status": str(p.status),
                "outcome": str(p.outcome),
                "quote_figure": figure,
                "quote_hours": quote,
                "no_moderator": p.no_moderator_since is not None,
                "created_at": p.created_at,
                "updated_at": updated,
                "money": _money_out(money.get(p.id)),
            }
        )
    last = page[-1]
    return items, ([last.created_at.isoformat(), str(last.id)] if more else None)


def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    known = [v for v in values if v is not None]
    return sum(known, Decimal(0)) if known else None


def _months(date_from: dt.date, date_to: dt.date) -> list[str]:
    out: list[str] = []
    year, month = date_from.year, date_from.month
    while (year, month) <= (date_to.year, date_to.month):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


async def _loss_reasons(db: AsyncSession, lost: Sequence[Project]) -> list[dict[str, Any]]:
    names = dict(
        (await db.execute(select(LossReason.id, LossReason.name).where(
            LossReason.id.in_({p.loss_reason_id for p in lost if p.loss_reason_id})
        ))).all()
    )  # fmt: skip
    groups: dict[uuid.UUID | None, list[Project]] = defaultdict(list)
    for p in lost:
        groups[p.loss_reason_id].append(p)
    out = [
        {
            "loss_reason_id": None if rid is None else str(rid),
            "name": NO_REASON if rid is None else names.get(rid, NO_REASON),
            "count": len(items),
            "texts": [p.loss_reason_text for p in items if p.loss_reason_text],
        }
        for rid, items in groups.items()
    ]
    return sorted(out, key=lambda r: (-r["count"], r["name"]))


async def _first_snapshot_days(db: AsyncSession, period: Sequence[Project]) -> str | None:
    if not period:
        return None
    rows = await db.execute(
        select(Snapshot.project_id, func.min(Snapshot.created_at))
        .where(Snapshot.project_id.in_([p.id for p in period]))
        .group_by(Snapshot.project_id)
    )
    first = dict(rows.all())
    days = [
        Decimal((first[p.id] - p.created_at).total_seconds()) / 86400
        for p in period
        if p.id in first
    ]
    if not days:
        return None
    return format_decimal(round_half_up(statistics.median(days), 1))


async def summary(db: AsyncSession, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    """Сводка по портфелю за период (FR-PORT-02, 11.13 №2–5)."""
    period = list(await db.scalars(select(Project).where(*await _period(db, date_from, date_to))))
    money = await portfolio_money(db, [p.id for p in period])
    zone = await app_timezone(db)

    def quote_rub(p: Project) -> Decimal | None:
        m = money.get(p.id)
        return None if m is None else m.quote_rub

    by = {o: [p for p in period if ProjectOutcome(p.outcome) is o] for o in ProjectOutcome}
    won, lost = by[ProjectOutcome.WON], by[ProjectOutcome.LOST]
    won_rub, lost_rub = _sum(map(quote_rub, won)), _sum(map(quote_rub, lost))
    ratios = []
    for p in won:
        m = money.get(p.id)
        if m is not None and m.contract_amount is not None and m.quote_cur:
            ratios.append(m.contract_amount * 100 / m.quote_cur)
    months: dict[str, dict[str, int]] = {
        k: {"won": 0, "lost": 0, "cancelled": 0} for k in _months(date_from, date_to)
    }
    for p in period:
        key = p.created_at.astimezone(zone).strftime("%Y-%m")
        outcome = str(p.outcome)
        if key in months and outcome in months[key]:
            months[key][outcome] += 1
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "by_status": {
            s.value: sum(1 for p in period if ProjectStatus(p.status) is s) for s in ProjectStatus
        },
        "by_outcome": {o.value: len(by[o]) for o in ProjectOutcome},
        "won_share_count_pct": _pct(len(won), len(won) + len(lost)),
        "won_share_money_pct": _pct(won_rub or 0, (won_rub or 0) + (lost_rub or 0)),
        "sum_won_cur": _money(won_rub),
        "sum_lost_cur": _money(lost_rub),
        "sum_in_progress_cur": _money(
            _sum(quote_rub(p) for p in period if ProjectStatus(p.status) in IN_PROGRESS)
        ),
        "loss_reasons": await _loss_reasons(db, lost),
        "contract_to_quote_median_pct": (
            format_decimal(round_half_up(statistics.median(ratios), 1)) if ratios else None
        ),
        "by_month": [{"month": k, **v} for k, v in months.items()],
        "first_snapshot_median_days": await _first_snapshot_days(db, period),
    }


__all__ = ["PortfolioFilter", "projects", "summary"]
