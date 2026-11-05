"""ADM-000: contracts/settings.schema.json покрывает ключи system_settings и умолчания SPEC."""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.unit._contracts import load_json, spec_text

pytestmark = pytest.mark.spec("14.2")

S = load_json("settings.schema.json")
PROPS: dict[str, dict] = S["properties"]
TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}  # fmt: skip


def _is(value: Any, t: str) -> bool:
    if t in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, TYPES[t])


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Подмножество JSON Schema 2020-12, которое использует контракт."""
    errs: list[str] = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_is(value, t) for t in types):
            return [f"{path}: тип {type(value).__name__} не из {types}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} не из enum")
    if isinstance(value, str):
        if len(value) > schema.get("maxLength", 10**9) or len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: длина")
        if "pattern" in schema and value and not re.search(schema["pattern"], value):
            errs.append(f"{path}: pattern")
    if _is(value, "number"):
        if value < schema.get("minimum", -(10**18)) or value > schema.get("maximum", 10**18):
            errs.append(f"{path}: диапазон")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: exclusiveMinimum")
        if "multipleOf" in schema and (value / schema["multipleOf"]) % 1:
            errs.append(f"{path}: multipleOf")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errs += [f"{path}: нет {k}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            errs += [f"{path}: лишний {k}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10**9):
            errs.append(f"{path}: maxItems")
        for i, v in enumerate(value):
            errs += validate(v, schema.get("items", {}), f"{path}[{i}]")
    return errs


def test_keys_cover_14_2():
    text = spec_text()
    listed = re.search(r"\*\*system_settings\*\* — .*", text).group(0)
    for prefix in re.findall(r"`([a-z_.]+?)(?:\.\*)?`", listed)[2:]:
        assert any(k == prefix or k.startswith(prefix + ".") for k in PROPS), prefix
    for prefix in ("method.",):  # app_params → method.* (14.2, DB-001)
        assert any(k.startswith(prefix) for k in PROPS)


@pytest.mark.parametrize("key", list(PROPS))
def test_default_is_valid(key: str):
    prop = PROPS[key]
    assert "default" in prop, key
    assert validate(prop["default"], prop) == [], key
    assert prop["x-owner"] in {"superadmin", "admin", "system"}
    assert prop["x-spec"]


def test_spec_defaults():
    d = {k: v["default"] for k, v in PROPS.items()}
    assert d["auth.mode"] == "local"
    assert d["auth.ad.connection"]["timeout_seconds"] == 5
    assert d["auth.ad.connection"]["user_filter"] == "(&(objectClass=user)(sAMAccountName={login}))"
    assert d["security.password_policy"]["min_length"] == 12
    assert d["security.password_policy"]["max_length"] == 128
    assert d["security.password_policy"]["history"] == 5
    assert d["security.session"] == {
        "idle_minutes_user": 60, "idle_minutes_admin": 15, "absolute_hours": 12,
    }  # fmt: skip
    assert d["security.lockout"] == {"max_failures": 5, "lock_minutes": 15}
    assert d["security.mfa_policy"]["user"] == "optional"
    assert {v for k, v in d["security.mfa_policy"].items() if k != "user"} == {"required"}
    assert d["retention.periods"]["audit_months"] == 12
    assert d["retention.periods"]["change_log_days"] == 7
    assert d["digest.time"] == "09:00"
    assert d["method.large_leaf_hours"] == {"medium": 80, "detailed": 40}
    assert d["method.medium_expected_units"] == {"min": 5, "max": 15}
    assert d["method.pm_percent_default"] == 18
    assert d["method.autoarchive_days"] == 180


def test_secrets_marked_and_ldap_plain_impossible():
    secrets = {k for k, v in PROPS.items() if v.get("x-secret")}
    assert secrets == {"auth.ad.bind_password", "smtp.password", "siem.client_key"}
    assert PROPS["auth.ad.connection"]["properties"]["protocol"]["enum"] == ["ldaps", "starttls"]
    assert validate(90, PROPS["retention.periods"]["properties"]["audit_months"]) == []
    assert validate(5, PROPS["retention.periods"]["properties"]["audit_months"]) != []


def test_superadmin_writes_need_step_up():
    for key, prop in PROPS.items():
        if prop["x-owner"] == "superadmin":
            assert prop.get("x-step-up") is True, key
