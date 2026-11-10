"""Контракт ключей настроек (ADM-000, ``contracts/settings.schema.json``) и проверка значений.

``jsonschema`` есть только в dev-зависимостях, поэтому здесь — проверка того подмножества JSON
Schema, которое использует контракт: ``type`` (в том числе список с ``null``), ``enum``,
``minimum``/``maximum``/``exclusiveMinimum``/``multipleOf``, ``minLength``/``maxLength``/
``pattern``, ``format`` (``email``, ``uri``, ``date-time``), ``properties``/``required``/
``additionalProperties: false``, ``items``/``maxItems``/``uniqueItems``. Неизвестное ключевое
слово роняет загрузку контракта, а не пропускается молча. Совпадение с ``jsonschema`` на
значениях по умолчанию и граничных случаях проверяет тест ``tests/unit/adm``.

Файл ищется рядом с модулем (образ кладёт его туда, как каталог прав) или в ``contracts/``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

FILE_NAME = "settings.schema.json"
ENV_PATH = "ESTIMATOR_SETTINGS_SCHEMA"

#: Ключевые слова JSON Schema, которые понимает :func:`errors`; аннотации не проверяются
KEYWORDS = frozenset({
    "type", "enum", "minimum", "maximum", "exclusiveMinimum", "multipleOf", "minLength",
    "maxLength", "pattern", "format", "properties", "required", "additionalProperties", "items",
    "maxItems", "uniqueItems",
})  # fmt: skip
ANNOTATIONS = frozenset({"title", "description", "default", "$comment"})
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SchemaError(RuntimeError):
    """Контракт настроек не найден или использует неподдержанное ключевое слово."""


def schema_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    packaged = Path(__file__).with_name(FILE_NAME)
    if packaged.is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / FILE_NAME
        if candidate.is_file():
            return candidate
    raise SchemaError(f"не найден {FILE_NAME}: ни рядом с модулем, ни в contracts/")


def _check_keywords(node: Mapping[str, Any], where: str) -> None:
    unknown = {k for k in node if not k.startswith("x-")} - KEYWORDS - ANNOTATIONS
    if unknown:
        raise SchemaError(f"{where}: неподдержанные ключевые слова {sorted(unknown)}")
    for name, child in (node.get("properties") or {}).items():
        _check_keywords(child, f"{where}.{name}")
    if isinstance(node.get("items"), Mapping):
        _check_keywords(node["items"], f"{where}[]")


@cache
def contract() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(schema_path().read_text(encoding="utf-8"))
    for key, node in data["properties"].items():
        _check_keywords(node, key)
    return data


def key_schema(key: str) -> dict[str, Any]:
    return contract()["properties"][key]  # type: ignore[no-any-return]


def keys() -> frozenset[str]:
    return frozenset(contract()["properties"])


def default(key: str) -> Any:
    return json.loads(json.dumps(key_schema(key).get("default")))  # копия


def is_secret(key: str) -> bool:
    return bool(key_schema(key).get("x-secret"))


def owner(key: str) -> str:
    return str(key_schema(key).get("x-owner", "superadmin"))


def section_keys(name: str) -> tuple[str, ...]:
    return tuple(contract()["x-sections"][name])


# --- проверка значения ---


def _type_ok(value: Any, kind: str) -> bool:
    match kind:
        case "null":
            return value is None
        case "boolean":
            return isinstance(value, bool)
        case "integer":
            return (isinstance(value, int) and not isinstance(value, bool)) or (
                isinstance(value, float) and value.is_integer()
            )
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "string":
            return isinstance(value, str)
        case "array":
            return isinstance(value, list)
        case "object":
            return isinstance(value, dict)
    raise SchemaError(f"неизвестный тип {kind!r}")


def _format_ok(value: str, fmt: str) -> bool:
    if fmt == "email":
        return bool(_EMAIL.match(value))
    if fmt == "uri":
        return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/?#]+[^\s]*$", value))
    if fmt == "date-time":
        try:
            dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return "T" in value or " " in value
    raise SchemaError(f"неизвестный format {fmt!r}")


def errors(node: Mapping[str, Any], value: Any, path: str = "") -> list[tuple[str, str]]:
    """Ошибки ``value`` по схеме ``node``: список пар (JSON Pointer, сообщение)."""
    kinds = node.get("type")
    if kinds is not None:
        allowed = [kinds] if isinstance(kinds, str) else list(kinds)
        if not any(_type_ok(value, k) for k in allowed):
            return [(path, f"ожидается {' или '.join(allowed)}")]
    if value is None:
        return []
    if "enum" in node and value not in node["enum"]:
        return [(path, "значение не из списка")]
    out: list[tuple[str, str]] = []
    if isinstance(value, int | float) and not isinstance(value, bool):
        number = Decimal(str(value))
        if "minimum" in node and number < Decimal(str(node["minimum"])):
            out.append((path, f"не меньше {node['minimum']}"))
        if "maximum" in node and number > Decimal(str(node["maximum"])):
            out.append((path, f"не больше {node['maximum']}"))
        if "exclusiveMinimum" in node and number <= Decimal(str(node["exclusiveMinimum"])):
            out.append((path, f"больше {node['exclusiveMinimum']}"))
        if "multipleOf" in node and number % Decimal(str(node["multipleOf"])) != 0:
            out.append((path, f"кратно {node['multipleOf']}"))
    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            out.append((path, f"не короче {node['minLength']} символов"))
        if "maxLength" in node and len(value) > node["maxLength"]:
            out.append((path, f"не длиннее {node['maxLength']} символов"))
        if "pattern" in node and not re.search(node["pattern"], value):
            out.append((path, "неверный формат"))
        if "format" in node and not _format_ok(value, node["format"]):
            out.append((path, f"неверный формат ({node['format']})"))
    if isinstance(value, list):
        if "maxItems" in node and len(value) > node["maxItems"]:
            out.append((path, f"не больше {node['maxItems']} элементов"))
        if node.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(seen) != len(set(seen)):
                out.append((path, "элементы повторяются"))
        if isinstance(node.get("items"), Mapping):
            for i, item in enumerate(value):
                out += errors(node["items"], item, f"{path}/{i}")
    if isinstance(value, dict):
        props: Mapping[str, Any] = node.get("properties") or {}
        out += [
            (f"{path}/{k}", "обязательное поле") for k in node.get("required", ()) if k not in value
        ]
        if node.get("additionalProperties") is False:
            out += [(f"{path}/{k}", "лишнее поле") for k in value if k not in props]
        for name, child in props.items():
            if name in value:
                out += errors(child, value[name], f"{path}/{name}")
    return out
