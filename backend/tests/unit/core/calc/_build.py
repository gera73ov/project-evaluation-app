"""Конструктор маленьких проектов для unit-тестов расчёта."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from estimator.domain.calc import (
    BranchStatus,
    DetailLevel,
    Discipline,
    MoneySettings,
    Node,
    NodeKind,
    Phase,
    ProjectInput,
    QuoteFigure,
)

D = Decimal


def leaf(
    node_id: str,
    parent: str,
    phase: str,
    discipline: str,
    orp: str | None,
    n: int = 1,
    type_name: str | None = None,
) -> Node:
    o = r = p = None
    if orp is not None:
        o, r, p = (D(v) for v in orp.split("-"))
    return Node(node_id, parent, NodeKind.ITEM, phase, discipline, type_name, node_id, o, r, p, n)


def branch(phase: str, discipline: str) -> list[Node]:
    return [Node(f"{phase}-{discipline}", phase, NodeKind.DISCIPLINE, phase, discipline)]


def project(
    nodes: Sequence[Node],
    *,
    phases: Sequence[Phase] | None = None,
    disciplines: Sequence[Discipline] = (Discipline("be", "Бэкенд"), Discipline("qa", "QA")),
    pm: str = "0",
    status: dict[tuple[str, str], BranchStatus] | None = None,
    money: MoneySettings | None = None,
    level: DetailLevel = DetailLevel.MEDIUM,
    quote: QuoteFigure = QuoteFigure.P80,
) -> ProjectInput:
    phases = phases or [Phase("a", "Разработка"), Phase("pm", "УП", is_cross_cutting=True)]
    roots = [Node(p.id, None, NodeKind.PHASE, p.id) for p in phases]
    return ProjectInput(
        pm_percent=D(pm),
        quote_figure=quote,
        detail_level=level,
        phases=phases,
        disciplines=disciplines,
        nodes=[*roots, *nodes],
        branch_status=status or {},
        money=money,
    )


def rub(rates: dict[str | None, str], vat: str | None = "20", rate: str = "1") -> MoneySettings:
    return MoneySettings(
        "RUB" if rate == "1" else "USD",
        D(rate),
        None if vat is None else D(vat),
        {k: D(v) for k, v in rates.items()},
    )
