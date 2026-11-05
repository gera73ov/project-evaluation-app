"""PM-001 · контракты этапа 0 согласованы между собой и заморожены в версии 1.0.0 (веха M0).

Проверяет то, что не видно из одного файла: один код ошибки на HTTP и WS, одна форма ссылки
на пользователя, эндпоинт для каждого раздела настроек администратора (GAP-13) и метку версии
в каждом контракте раздела 6 PLAN.md.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.unit._contracts import CONTRACTS, load_json, load_yaml

RELEASE = "1.0.0"
OPENAPI = load_yaml("openapi.yaml")
WS = load_json("ws-events.schema.json")
ERROR_CODES = {e["code"] for e in load_yaml("errors.yaml")["errors"]}


def _resolve(schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    return OPENAPI["components"]["schemas"][ref.rsplit("/", 1)[1]]


def _shape(schema: dict[str, Any]) -> dict[str, Any]:
    """Имена, типы и обязательность полей — то, что видит клиент."""
    props = {name: _resolve(value).get("type") for name, value in schema["properties"].items()}
    return {"properties": props, "required": sorted(schema["required"])}


@pytest.mark.spec("15.4")
def test_ws_error_codes_come_from_errors_yaml() -> None:
    text = (CONTRACTS / "ws-events.md").read_text(encoding="utf-8")
    section = text[text.index("Коды в `error.code`") :].split("\n\n", 1)[0]
    codes = set(re.findall(r"`([A-Z][A-Z_]+)`", section))
    assert codes, "в ws-events.md не найден список кодов ошибок"
    assert not codes - ERROR_CODES, f"коды не из errors.yaml: {sorted(codes - ERROR_CODES)}"


def test_user_ref_is_the_same_in_rest_and_ws() -> None:
    rest = _shape(OPENAPI["components"]["schemas"]["UserRef"])
    ws = _shape(WS["$defs"]["UserRef"])
    assert rest == ws


@pytest.mark.spec("7.5")
def test_method_settings_endpoint_covers_settings_section() -> None:
    settings = load_json("settings.schema.json")
    keys = {k.removeprefix("method.") for k in settings["x-sections"]["method"]}
    schema = OPENAPI["components"]["schemas"]["MethodSettings"]
    assert set(schema["properties"]) == keys
    ops = OPENAPI["paths"]["/admin/method-settings"]
    assert ops["get"]["x-permission"] == "dict.read"
    assert ops["put"]["x-permission"] == "dict.write"
    assert {ops["get"]["x-spec-gap"], ops["put"]["x-spec-gap"]} == {"GAP-13"}


YAML_CONTRACTS = [
    "permissions.yaml", "audit-events.yaml", "notifications.yaml", "exports.yaml", "errors.yaml",
]  # fmt: skip
JSON_CONTRACTS = ["ws-events.schema.json", "settings.schema.json"]
MARKDOWN_CONTRACTS = [
    "api-conventions.md", "db/schema.md", "fixtures/calc/README.md", "permissions.md",
    "ws-events.md",
]  # fmt: skip


@pytest.mark.parametrize("name", YAML_CONTRACTS)
def test_yaml_contract_is_released(name: str) -> None:
    data = load_yaml(name)
    assert str(data["version"]) == RELEASE
    assert data["status"] == "approved"


@pytest.mark.parametrize("name", JSON_CONTRACTS)
def test_json_contract_is_released(name: str) -> None:
    data = load_json(name)
    assert data["x-version"] == RELEASE
    assert data["x-status"] == "approved"


def test_openapi_is_released() -> None:
    assert OPENAPI["info"]["version"] == RELEASE


@pytest.mark.parametrize("name", MARKDOWN_CONTRACTS)
def test_markdown_contract_is_released(name: str) -> None:
    head = "\n".join((CONTRACTS / name).read_text(encoding="utf-8").splitlines()[:6])
    assert "черновик" not in head
    assert re.search(r"1\.0(\.0)?\b", head), "в шапке нет версии 1.0"
