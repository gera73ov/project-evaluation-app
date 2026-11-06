"""Десятичные числа строками (API-003; contracts/api-conventions.md 2.1, SPEC 15.1).

``DecimalString`` в схеме pydantic принимает строку с точкой или запятой (``"12,5"`` → ``12.5``) и
отдаёт строку без лишних нулей справа (``Decimal("16.00")`` → ``"16"``). Числа JSON на входе не
принимаются: точность теряется ещё в JavaScript (15.1). Округление до 0,5 и диапазоны — дело
предметной области (CORE), не транспорта.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

_PATTERN = re.compile(r"^-?\d+([.,]\d+)?$")
#: Шаблон OpenAPI для ответа (contracts/openapi.yaml, схема DecimalString)
JSON_PATTERN = r"^-?\d+(\.\d+)?$"


def parse_decimal(value: Any) -> Decimal:
    """Строка ``"12,5"`` или ``"12.5"`` → ``Decimal``; иначе ``ValueError`` (→ 422)."""
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str) or not _PATTERN.fullmatch(value.strip()):
        raise ValueError('ожидается десятичное число строкой, например "12.5"')
    try:
        return Decimal(value.strip().replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover — шаблон уже отсёк
        raise ValueError("некорректное десятичное число") from exc


def format_decimal(value: Decimal) -> str:
    """``Decimal`` → строка без экспоненты и лишних нулей.

    ``16.00`` → ``"16"``, ``0.50`` → ``"0.5"``.
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


DecimalString = Annotated[
    Decimal,
    BeforeValidator(parse_decimal),
    PlainSerializer(format_decimal, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": JSON_PATTERN}),
]
