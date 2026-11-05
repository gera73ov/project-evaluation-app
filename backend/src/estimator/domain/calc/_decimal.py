"""Общая десятичная арифметика расчётного модуля (SPEC 6, BR-CALC-03).

Промежуточные значения не округляются: все вычисления идут в контексте ``CALC_CONTEXT`` с
40 значащими цифрами (с запасом для 11 · 99 999,5 · 10 000 · 1 000 000 ₽). Округление — только
при выводе и только по ROUND_HALF_UP (``round_half_up``). Клиент (FE-002, decimal.js) использует
те же точность и правила, поэтому результаты совпадают знак в знак.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, localcontext
from functools import wraps
from typing import ParamSpec, TypeVar

PRECISION = 40
CALC_CONTEXT = Context(prec=PRECISION, rounding=ROUND_HALF_EVEN)

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

# z-квантили нормального распределения (SPEC 6.2) — константы, а не вычисляемые значения
Z80 = Decimal("0.8416")
Z90 = Decimal("1.2816")

_P = ParamSpec("_P")
_R = TypeVar("_R")


def in_calc_context[**P, R](func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Выполнить функцию в контексте ``CALC_CONTEXT`` (не зависит от контекста вызывающего)."""

    @wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with localcontext(CALC_CONTEXT):
            return func(*args, **kwargs)

    return wrapper


# Шум последних знаков: √(13 225/36) = 115/6 точно, но корень в 40 знаках даёт 19,1666…67, и
# σ_УП = 0,18 · σ выходит 3,4500…001. Если бы шум был вниз (3,4499…9), ROUND_HALF_UP дал бы 3,4.
# Поэтому перед округлением для вывода значение приводится к 20 знакам после запятой.
GUARD_PLACES = 20
_WIDE = Context(prec=PRECISION + GUARD_PLACES, rounding=ROUND_HALF_EVEN)


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Округлить до ``places`` знаков после запятой по ROUND_HALF_UP (0,05 → 0,1; 3,45 → 3,5)."""
    guarded = value.quantize(ONE.scaleb(-GUARD_PLACES), context=_WIDE)
    return guarded.quantize(ONE.scaleb(-places), rounding=ROUND_HALF_UP, context=_WIDE)


@in_calc_context
def sqrt(value: Decimal) -> Decimal:
    """Квадратный корень с точностью ``PRECISION`` значащих цифр."""
    return value.sqrt()


def p80(e: Decimal, sigma: Decimal) -> Decimal:
    """P80 = E + 0,8416·σ (SPEC 6.2)."""
    return CALC_CONTEXT.add(e, CALC_CONTEXT.multiply(Z80, sigma))


def p90(e: Decimal, sigma: Decimal) -> Decimal:
    """P90 = E + 1,2816·σ (SPEC 6.2)."""
    return CALC_CONTEXT.add(e, CALC_CONTEXT.multiply(Z90, sigma))
