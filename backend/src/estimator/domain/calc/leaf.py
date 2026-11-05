"""CORE-002 · расчёт листа (SPEC 6.1, BR-CALC-02…04, FR-TREE-21, NFR-LIM-01).

Чистые функции на ``Decimal``: оценка одной штуки по PERT, умножение на ×N (σ — на N, а не на √N),
классификация листа и нормализация ввода (шаг 0,5 ч по ROUND_HALF_UP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from estimator.domain.calc._decimal import CALC_CONTEXT, ZERO, in_calc_context, p80, p90

HOURS_MIN = ZERO
HOURS_MAX = Decimal("99999.5")
MULTIPLIER_MIN = 1
MULTIPLIER_MAX = 10_000

_HOURS_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_MULTIPLIER_RE = re.compile(r"\d+")
_TWO = Decimal(2)
_FOUR = Decimal(4)
_SIX = Decimal(6)


class LeafState(StrEnum):
    """Состояние оценки листа (BR-CALC-02, BR-CALC-04)."""

    EMPTY = "empty"  # нет хотя бы одного из O, R, P
    INVALID = "invalid"  # O > R или R > P
    ZERO = "zero"  # 0–0–0: «работа есть, трудозатрат не требует», выделяется серым
    VALID = "valid"

    @property
    def counted(self) -> bool:
        """Входит ли лист в суммы (пустые и неверные — нет, BR-CALC-02)."""
        return self in (LeafState.VALID, LeafState.ZERO)


class CalcInputError(ValueError):
    """Ввод не прошёл проверку; ``code`` — код ошибки из contracts/errors.yaml."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NormalizedHours:
    value: Decimal
    rounded: bool  # ввод округлён до шага 0,5 — у поля показывается подсказка

    @property
    def text(self) -> str:
        """Каноническая строка без лишних нулей: ``"12"``, ``"12.5"``."""
        return format(self.value.normalize(CALC_CONTEXT), "f")


@dataclass(frozen=True, slots=True)
class LeafEstimate:
    state: LeafState
    e_unit: Decimal
    sigma_unit: Decimal
    e: Decimal
    sigma: Decimal
    sum_o: Decimal = ZERO  # N·O, N·R, N·P — подсказка узла и «Свернуть в лист» (BR-TREE-03)
    sum_r: Decimal = ZERO
    sum_p: Decimal = ZERO

    @property
    def p80(self) -> Decimal:
        return p80(self.e, self.sigma)

    @property
    def p90(self) -> Decimal:
        return p90(self.e, self.sigma)


def classify(o: Decimal | None, r: Decimal | None, p: Decimal | None) -> LeafState:
    if o is None or r is None or p is None:
        return LeafState.EMPTY
    if o > r or r > p:
        return LeafState.INVALID
    if o == r == p == ZERO:
        return LeafState.ZERO
    return LeafState.VALID


@in_calc_context
def estimate(
    o: Decimal | None, r: Decimal | None, p: Decimal | None, multiplier: int
) -> LeafEstimate:
    """E и σ листа; для пустого и неверного листа значения нулевые и в суммы не идут."""
    if o is None or r is None or p is None:
        return LeafEstimate(LeafState.EMPTY, ZERO, ZERO, ZERO, ZERO)
    state = classify(o, r, p)
    if not state.counted:
        return LeafEstimate(state, ZERO, ZERO, ZERO, ZERO)
    e_unit = (o + _FOUR * r + p) / _SIX
    sigma_unit = (p - o) / _SIX
    n = Decimal(multiplier)
    return LeafEstimate(state, e_unit, sigma_unit, n * e_unit, n * sigma_unit, n * o, n * r, n * p)


def normalize_hours(raw: str) -> NormalizedHours:
    """Нормализовать ввод часов: запятая или точка, шаг 0,5 по ROUND_HALF_UP, 0–99 999,5.

    Диапазон проверяется после округления (BR-CALC-03, FR-TREE-21).
    """
    text = raw.strip()
    if not _HOURS_RE.fullmatch(text):
        raise CalcInputError("VALIDATION_FAILED", f"не число: {raw!r}")
    value = Decimal(text.replace(",", "."))
    stepped = (value * _TWO).quantize(Decimal(1), rounding=ROUND_HALF_UP) / _TWO
    if stepped < HOURS_MIN or stepped > HOURS_MAX:
        raise CalcInputError("VALUE_OUT_OF_RANGE", f"часы вне диапазона 0–99 999,5: {raw!r}")
    if stepped == ZERO:
        stepped = ZERO  # «-0» → «0»
    return NormalizedHours(stepped, stepped != value)


def validate_multiplier(raw: object) -> int:
    """×N — целое 1–10 000 (NFR-LIM-01); строка допускается, если в ней только цифры."""
    if isinstance(raw, str) and _MULTIPLIER_RE.fullmatch(raw.strip()):
        raw = int(raw.strip())
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise CalcInputError("VALIDATION_FAILED", f"×N — целое число: {raw!r}")
    if not MULTIPLIER_MIN <= raw <= MULTIPLIER_MAX:
        raise CalcInputError("VALUE_OUT_OF_RANGE", f"×N вне диапазона 1–10 000: {raw}")
    return raw
