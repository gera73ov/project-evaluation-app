"""Расчётный модуль сервера (трек CORE, SPEC раздел 6): чистые функции на ``Decimal``.

Порядок: ``ProjectInput`` → ``calculate`` (листья, свёртка, работы, УП, итог) →
``calculate_money`` (деньги по E, P80, P90) и функции ``analytics`` (доли, соотношения, объёмы,
кандидаты на декомпозицию). Клиентская копия — ``frontend/src/shared/calc`` (FE-002); обе
проверяются одними фикстурами ``contracts/fixtures/calc``.
"""

from estimator.domain.calc._decimal import Z80, Z90, round_half_up
from estimator.domain.calc.leaf import (
    CalcInputError,
    LeafEstimate,
    LeafState,
    classify,
    estimate,
    normalize_hours,
    validate_multiplier,
)
from estimator.domain.calc.model import (
    PM_ROW,
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
from estimator.domain.calc.money import (
    FigureMoney,
    MoneyResult,
    ProjectCache,
    calculate_money,
    fits_hours_cache,
    fits_money,
    project_cache,
)
from estimator.domain.calc.project import Figures, PmResult, ProjectResult, calculate
from estimator.domain.calc.rollup import CollapseSuggestion, Totals, TreeError, TreeResult, rollup

__all__ = [
    "PM_ROW",
    "Z80",
    "Z90",
    "BranchStatus",
    "CalcInputError",
    "CollapseSuggestion",
    "DetailLevel",
    "Discipline",
    "FigureMoney",
    "Figures",
    "LeafEstimate",
    "LeafState",
    "MoneyResult",
    "MoneySettings",
    "Node",
    "NodeKind",
    "Phase",
    "PmResult",
    "ProjectCache",
    "ProjectInput",
    "ProjectResult",
    "QuoteFigure",
    "Totals",
    "TreeError",
    "TreeResult",
    "calculate",
    "calculate_money",
    "classify",
    "estimate",
    "fits_hours_cache",
    "fits_money",
    "normalize_hours",
    "project_cache",
    "rollup",
    "round_half_up",
    "validate_multiplier",
]
