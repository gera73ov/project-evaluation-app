"""CORE-004 · управление проектом и итог проекта (SPEC 6.3, BR-CALC-05, BR-CALC-03, Q-42).

``E_УП = k·E_базы``, ``σ_УП = k·σ_базы``, ``σ_итог = σ_работ + σ_УП`` (УП полностью коррелирует
со своей базой). Сквозная фаза «Управление проектом» в работы не входит.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from estimator.domain.calc._decimal import HUNDRED, ZERO, in_calc_context, p80, p90
from estimator.domain.calc.model import ProjectInput
from estimator.domain.calc.rollup import Totals, TreeResult, rollup


@dataclass(frozen=True, slots=True)
class Figures:
    """E, σ, P80 и P90 группы (работы, УП, итог, фаза, дисциплина)."""

    e: Decimal
    sigma: Decimal

    @property
    def p80(self) -> Decimal:
        return p80(self.e, self.sigma)

    @property
    def p90(self) -> Decimal:
        return p90(self.e, self.sigma)

    @classmethod
    def of(cls, totals: Totals) -> Figures:
        return cls(totals.e, totals.sigma)


@dataclass(frozen=True, slots=True)
class PmResult(Figures):
    base_e: Decimal = ZERO
    base_sigma: Decimal = ZERO
    k: Decimal = ZERO  # доля УП (0,18 при 18%)

    @property
    def enabled(self) -> bool:
        return self.k > ZERO


@dataclass(frozen=True, slots=True)
class ProjectResult:
    input: ProjectInput
    tree: TreeResult
    phases: dict[str, Figures]  # фазы работ в порядке входа (без сквозной фазы УП)
    disciplines: dict[str, Figures]  # свёртка дисциплины через все фазы работ
    discipline_by_phase: dict[str, dict[str, Figures]]  # фаза → дисциплина → значения
    works: Figures
    pm: PmResult
    total: Figures
    unaccounted_leaves: int

    @property
    def p80_ratio(self) -> Decimal | None:
        """P80/E проекта; при E = 0 не вычисляется (BR-CALC-03)."""
        return None if self.total.e == ZERO else self.total.p80 / self.total.e

    @property
    def p90_ratio(self) -> Decimal | None:
        return None if self.total.e == ZERO else self.total.p90 / self.total.e

    def unaccounted_warning(self) -> str | None:
        """Текст верхней полосы «3 листа без оценки не учтены» (BR-CALC-02)."""
        return unaccounted_text(self.unaccounted_leaves) if self.unaccounted_leaves else None


def unaccounted_text(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} лист без оценки не учтён"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} листа без оценки не учтены"
    return f"{count} листов без оценки не учтены"


@in_calc_context
def calculate(project: ProjectInput) -> ProjectResult:
    """Полный расчёт часов проекта: дерево, фазы, дисциплины, работы, УП, итог."""
    tree = rollup(project)
    phase_nodes = {r.node.phase_id: r for r in tree.nodes.values() if r.node.parent_id is None}
    work_phases = [p for p in project.phases if p.enabled and not p.is_cross_cutting]
    phases: dict[str, Figures] = {}
    works = Totals()
    base = Totals()
    unaccounted = 0
    for phase in work_phases:
        node = phase_nodes.get(phase.id)
        totals = node.totals if node is not None else Totals()
        phases[phase.id] = Figures.of(totals)
        works.add(totals)
        if phase.in_pm_base:
            base.add(totals)
    for phase in project.phases:
        node = phase_nodes.get(phase.id)
        if phase.enabled and node is not None:
            unaccounted += node.totals.unaccounted

    by_discipline: dict[str, Totals] = {d.id: Totals() for d in project.disciplines}
    by_phase: dict[str, dict[str, Totals]] = {
        p.id: {d.id: Totals() for d in project.disciplines} for p in work_phases
    }
    for leaf in tree.leaves():
        node = leaf.node
        if node.phase_id not in by_phase or node.discipline_id not in by_discipline:
            continue  # сквозная фаза УП или дисциплина вне списка проекта
        by_discipline[node.discipline_id].add(leaf.totals)
        by_phase[node.phase_id][node.discipline_id].add(leaf.totals)

    k = project.pm_percent / HUNDRED
    base_sigma = base.sigma
    pm = PmResult(e=k * base.e, sigma=k * base_sigma, base_e=base.e, base_sigma=base_sigma, k=k)
    works_figures = Figures.of(works)
    total = Figures(works.e + pm.e, works_figures.sigma + pm.sigma)
    return ProjectResult(
        input=project,
        tree=tree,
        phases=phases,
        disciplines={d: Figures.of(t) for d, t in by_discipline.items()},
        discipline_by_phase={
            ph: {d: Figures.of(t) for d, t in row.items()} for ph, row in by_phase.items()
        },
        works=works_figures,
        pm=pm,
        total=total,
        unaccounted_leaves=unaccounted,
    )
