"""API-003: DecimalString — ввод с запятой или точкой, вывод строкой без лишних нулей (15.1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from estimator.api.common import DecimalString

pytestmark = pytest.mark.spec("15.1")


class M(BaseModel):
    r: DecimalString


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("12.5", Decimal("12.5")),
        ("12,5", Decimal("12.5")),
        ("16", Decimal(16)),
        (" 0,5 ", Decimal("0.5")),
    ],
)
def test_parse(raw: str, value: Decimal) -> None:
    assert M(r=raw).r == value


@pytest.mark.parametrize("raw", [12.5, 16, "1e3", "12.", ",5", "abc", "", None, "1.2.3"])
def test_reject(raw: object) -> None:
    with pytest.raises(ValidationError):
        M(r=raw)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("16.00"), "16"),
        (Decimal("0.50"), "0.5"),
        (Decimal("1E+3"), "1000"),
        (Decimal("-0.0"), "0"),
    ],
)
def test_serialize(value: Decimal, text: str) -> None:
    assert M(r=value).model_dump(mode="json") == {"r": text}


def test_json_schema_is_string() -> None:
    assert M.model_json_schema()["properties"]["r"]["type"] == "string"
