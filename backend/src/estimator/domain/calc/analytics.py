"""CORE-006 · доли, контрольные соотношения, «крупные» листья, объёмы (SPEC 6.6, BR-TREE-09,
C-27, 5.2, 10.1, 11.10).

Всё здесь — подсказки статистики: ничего не блокируется. Пороги «крупного» листа — настройки
``method.large_leaf_hours`` (contracts/settings.schema.json), сравнивается E одной штуки.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from estimator.domain.calc._decimal import HUNDRED, ZERO, in_calc_context
from estimator.domain.calc.leaf import LeafEstimate
from estimator.domain.calc.model import DetailLevel, Node
from estimator.domain.calc.project import ProjectResult

WORK_TYPE = "Работа"  # тип по умолчанию, если у листа тип не задан (BR-TREE-08)
WIDE_FORK_RATIO = Decimal("0.3")  # σ/E > 30% — «↔ широкая вилка» (10.1)
TOP_N = 10
DEFAULT_LARGE_LEAF_HOURS: Mapping[DetailLevel, Decimal | None] = {
    DetailLevel.COARSE: None,  # для «Крупно» порога нет (5.2)
    DetailLevel.MEDIUM: Decimal(80),
    DetailLevel.DETAILED: Decimal(40),
}


class Verdict(StrEnum):
    BELOW = "below"
    WITHIN = "within"
    ABOVE = "above"


@dataclass(frozen=True, slots=True)
class Shares:
    """Доли в процентах без округления; ``None`` — знаменатель 0, показывается «—»."""

    disciplines: dict[str, Decimal | None]  # доля дисциплины в часах работ
    by_phase: dict[str, dict[str, Decimal | None]]  # фаза → доля дисциплины в фазе
    phases: dict[str, Decimal | None]  # доля фазы в итоге проекта


@dataclass(frozen=True, slots=True)
class ControlRatio:
    discipline_a: str
    disciplines_b: tuple[str, ...]
    min_pct: Decimal
    max_pct: Decimal
    pct: Decimal | None  # None — у дисциплин B нет часов
    verdict: Verdict | None


@dataclass(frozen=True, slots=True)
class Candidate:
    node_id: str
    e_unit: Decimal
    e: Decimal
    sigma_ratio: Decimal | None  # σ/E листа, None при E = 0
    large: bool  # E одной штуки выше порога
    repeating: bool  # ×N > 1, E одной штуки не выше порога, E листа выше
    wide_fork: bool  # σ/E > 30%


@dataclass(frozen=True, slots=True)
class Decomposition:
    threshold_hours: Decimal | None
    large: list[str]
    repeating: list[str]
    wide_forks: list[str]
    top_by_e: list[Candidate]  # топ-10 по E (11.10 №3)
    top_by_sigma_ratio: list[Candidate]  # топ-10 по σ/E


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return None if whole == ZERO else part / whole * HUNDRED


@in_calc_context
def shares(project: ProjectResult) -> Shares:
    works_e = project.works.e
    return Shares(
        disciplines={d: _pct(f.e, works_e) for d, f in project.disciplines.items()},
        by_phase={
            phase: {d: _pct(f.e, project.phases[phase].e) for d, f in row.items()}
            for phase, row in project.discipline_by_phase.items()
        },
        phases={phase: _pct(f.e, project.total.e) for phase, f in project.phases.items()},
    )


@in_calc_context
def control_ratio(
    project: ProjectResult,
    discipline_a: str,
    disciplines_b: Sequence[str],
    min_pct: Decimal,
    max_pct: Decimal,
) -> ControlRatio:
    """«A к ΣB» (6.6): границы диапазона включаются в норму."""
    figures_a = project.disciplines.get(discipline_a)
    a = figures_a.e if figures_a is not None else ZERO
    b = sum((project.disciplines[d].e for d in disciplines_b if d in project.disciplines), ZERO)
    pct = _pct(a, b)
    verdict = None
    if pct is not None:
        verdict = (
            Verdict.BELOW if pct < min_pct else Verdict.ABOVE if pct > max_pct else Verdict.WITHIN
        )
    return ControlRatio(discipline_a, tuple(disciplines_b), min_pct, max_pct, pct, verdict)


def volumes(project: ProjectResult) -> dict[str, int]:
    """Объёмы по типам с учётом ×N (10.1). Узлы-группы не считаются — только листья."""
    result: dict[str, int] = {}
    for leaf in project.tree.leaves():
        type_name = leaf.node.type or WORK_TYPE
        result[type_name] = result.get(type_name, 0) + leaf.node.multiplier
    return result


def volumes_text(volumes_by_type: Mapping[str, int]) -> str:
    """Строка-сводка для КП: «Экран — 13, Функция — 2» (11.10 №2)."""
    return ", ".join(f"{name} — {count}" for name, count in volumes_by_type.items())


def large_leaf_threshold(
    level: DetailLevel, thresholds: Mapping[DetailLevel, Decimal | None] | None = None
) -> Decimal | None:
    return (thresholds or DEFAULT_LARGE_LEAF_HOURS).get(level)


@in_calc_context
def _candidate(node: Node, estimate: LeafEstimate, threshold: Decimal | None) -> Candidate:
    ratio = None if estimate.e == ZERO else estimate.sigma / estimate.e
    large = threshold is not None and estimate.e_unit > threshold
    repeating = (
        threshold is not None and not large and node.multiplier > 1 and estimate.e > threshold
    )
    return Candidate(
        node_id=node.id,
        e_unit=estimate.e_unit,
        e=estimate.e,
        sigma_ratio=ratio,
        large=large,
        repeating=repeating,
        wide_fork=ratio is not None and ratio > WIDE_FORK_RATIO,
    )


def decomposition(
    project: ProjectResult,
    thresholds: Mapping[DetailLevel, Decimal | None] | None = None,
) -> Decomposition:
    """«Кандидаты на декомпозицию» и флажки ◆ / ↔ (BR-TREE-09, C-27, 10.1, 11.10 №3)."""
    threshold = large_leaf_threshold(project.input.detail_level, thresholds)
    candidates = [
        _candidate(leaf.node, leaf.leaf, threshold)
        for leaf in project.tree.leaves()
        if leaf.leaf is not None and leaf.leaf.state.counted
    ]
    by_ratio = [c for c in candidates if c.sigma_ratio is not None]
    return Decomposition(
        threshold_hours=threshold,
        large=[c.node_id for c in candidates if c.large],
        repeating=[c.node_id for c in candidates if c.repeating],
        wide_forks=[c.node_id for c in candidates if c.wide_fork],
        top_by_e=sorted(candidates, key=lambda c: c.e, reverse=True)[:TOP_N],
        top_by_sigma_ratio=sorted(by_ratio, key=lambda c: c.sigma_ratio or ZERO, reverse=True)[
            :TOP_N
        ],
    )
