"""ADM-002: проверка значений настроек по contracts/settings.schema.json совпадает с jsonschema
(в приложении jsonschema нет — см. estimator.admin.settings.schema)."""

from __future__ import annotations

import copy
from typing import Any

import jsonschema
import pytest

from estimator.admin.settings import schema

pytestmark = pytest.mark.spec("7.1")


def _reference_ok(node: dict[str, Any], value: Any) -> bool:
    validator = jsonschema.Draft202012Validator(
        node, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
    return not list(validator.iter_errors(value))


def _mutations(node: dict[str, Any], value: Any) -> list[Any]:
    """Значения рядом с границами схемы: и допустимые, и нет."""
    out: list[Any] = [None, "x", 1, 1.5, True, [], {}]
    if isinstance(value, dict):
        for name, child in (node.get("properties") or {}).items():
            for variant in _mutations(child, value.get(name)):
                changed = copy.deepcopy(value)
                changed[name] = variant
                out.append(changed)
            missing = copy.deepcopy(value)
            missing.pop(name, None)
            out.append(missing)
        out.append({**value, "extra": 1})
    for bound in ("minimum", "maximum", "exclusiveMinimum"):
        if bound in node:
            out += [node[bound], node[bound] - 1, node[bound] + 1]
    if "multipleOf" in node:
        out += [node["multipleOf"] * 3, node["multipleOf"] * 1.5]
    if "maxLength" in node:
        out += ["a" * node["maxLength"], "a" * (node["maxLength"] + 1)]
    if "minLength" in node:
        out += ["a" * node["minLength"], "a" * max(node["minLength"] - 1, 0)]
    if "enum" in node:
        out += [*node["enum"], "другое"]
    if node.get("format") == "email":
        out += ["a@b.ru", "нет-собаки"]
    if node.get("format") == "uri" or "pattern" in node:
        out += [
            "https://est.corp",
            "http://est.corp",
            "-----BEGIN CERTIFICATE-----\nAA",
            "10.0.0.0/8",
        ]
    if node.get("format") == "date-time":
        out += ["2026-11-10T09:00:00Z", "10.11.2026"]
    if node.get("type") == "array" or "array" in (node.get("type") or ()):
        out += [["a", "a"], ["a"], [1]]
    return out


@pytest.mark.parametrize("key", sorted(schema.keys()))
def test_validator_agrees_with_jsonschema(key: str) -> None:
    node = schema.key_schema(key)
    default = schema.default(key)
    assert schema.errors(node, default) == [], key
    for value in _mutations(node, default):
        mine = not schema.errors(node, value)
        assert mine == _reference_ok(node, value), (key, value)
