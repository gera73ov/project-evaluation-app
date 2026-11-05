"""Входные данные расчёта: проект, фазы, дисциплины, плоский список узлов (SPEC 14.3).

Формат совпадает с ``input`` эталонных фикстур ``contracts/fixtures/calc`` (CORE-001): десятичные
значения — строки, ×N — целое. Сервис дерева (CORE-010) собирает этот же объект из БД, поэтому
модуль не зависит ни от SQLAlchemy, ни от API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

PM_ROW = "pm"  # ключ строки «Управление проектом» в денежных строках


class NodeKind(StrEnum):
    PHASE = "phase"
    DISCIPLINE = "discipline"
    ITEM = "item"


class BranchStatus(StrEnum):
    NOT_STARTED = "not_started"
    DRAFT = "draft"
    DONE = "done"
    NOT_NEEDED = "not_needed"


class QuoteFigure(StrEnum):
    E = "e"
    P80 = "p80"
    P90 = "p90"


class DetailLevel(StrEnum):
    COARSE = "coarse"
    MEDIUM = "medium"
    DETAILED = "detailed"


@dataclass(frozen=True, slots=True)
class Phase:
    id: str
    name: str
    is_cross_cutting: bool = False
    in_pm_base: bool = True
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Discipline:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    parent_id: str | None
    kind: NodeKind
    phase_id: str
    discipline_id: str | None = None
    type: str | None = None
    title: str = ""
    o: Decimal | None = None
    r: Decimal | None = None
    p: Decimal | None = None
    multiplier: int = 1


@dataclass(frozen=True, slots=True)
class MoneySettings:
    currency: str
    exchange_rate: Decimal
    vat_percent: Decimal | None
    # дисциплина → ставка ₽/ч; ключ None — ставка УП. Нет ключа — ставка не задана
    rates: Mapping[str | None, Decimal] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProjectInput:
    pm_percent: Decimal
    quote_figure: QuoteFigure
    detail_level: DetailLevel
    phases: Sequence[Phase]
    disciplines: Sequence[Discipline]
    nodes: Sequence[Node]
    branch_status: Mapping[tuple[str, str], BranchStatus] = field(default_factory=dict)
    money: MoneySettings | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProjectInput:
        """Собрать вход из словаря формата фикстур (contracts/fixtures/calc/README.md 1.1)."""
        project = data["project"]
        money = data.get("money")
        return cls(
            pm_percent=Decimal(project["pm_percent"]),
            quote_figure=QuoteFigure(project["quote_figure"]),
            detail_level=DetailLevel(project["detail_level"]),
            phases=[
                Phase(
                    id=p["id"],
                    name=p["name"],
                    is_cross_cutting=p["is_cross_cutting"],
                    in_pm_base=p["in_pm_base"],
                    enabled=p["enabled"],
                )
                for p in data["phases"]
            ],
            disciplines=[Discipline(id=d["id"], name=d["name"]) for d in data["disciplines"]],
            nodes=[_node(n) for n in data["nodes"]],
            branch_status={
                (b["phase_id"], b["discipline_id"]): BranchStatus(b["status"])
                for b in data.get("branch_status", [])
            },
            money=None if money is None else _money(money),
        )


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _node(data: Mapping[str, Any]) -> Node:
    return Node(
        id=data["id"],
        parent_id=data["parent_id"],
        kind=NodeKind(data["kind"]),
        phase_id=data["phase_id"],
        discipline_id=data.get("discipline_id"),
        type=data.get("type"),
        title=data.get("title", ""),
        o=_optional_decimal(data.get("o")),
        r=_optional_decimal(data.get("r")),
        p=_optional_decimal(data.get("p")),
        multiplier=data.get("multiplier", 1),
    )


def _money(data: Mapping[str, Any]) -> MoneySettings:
    return MoneySettings(
        currency=data["currency"],
        exchange_rate=Decimal(data["exchange_rate"]),
        vat_percent=_optional_decimal(data["vat_percent"]),
        rates={r["discipline_id"]: Decimal(r["rate_rub"]) for r in data.get("rates", [])},
    )
