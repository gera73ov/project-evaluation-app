"""Сверка реализации API с contracts/openapi.yaml (API-004; SPEC 15.1, 15.2).

Две проверки на одном описании контракта:

* :func:`compare_operation` — статическая: OpenAPI, который строит FastAPI, против контракта
  оператор за оператором (путь и метод, право, step-up, успешные коды, параметры, схема тела
  запроса и успешного ответа). Её гоняет ``test_openapi_implementation.py``.
* :func:`check_response` — по живому трафику: каждый ответ API-тестов сверяется с контрактом
  (код объявлен у операции, тело проходит схему, ошибки — ``application/problem+json``). Её
  подключает фикстура ``api`` (``tests/integration/auth/conftest.py``) хуком httpx.

Схемы сравниваются после нормализации: ``$ref`` раскрываются, остаются тип, перечисления,
свойства, обязательные поля и элементы массивов. Описания, примеры и форматы не сравниваются.
Необязательное поле запроса ``X | None`` (так pydantic пишет поле со значением по умолчанию
``None``) считается равным полю ``X`` контракта: отсутствие поля и ``null`` сервер понимает
одинаково.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "contracts" / "openapi.yaml"
API_PREFIX = "/api/v1"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
PROBLEM_JSON = "application/problem+json"
_MAX_DEPTH = 12
#: Коды транспорта, общие для операций с телом (api-conventions.md 11): операции их не
#: перечисляют, тело сверяется со схемой Problem
BODY_TRANSPORT_CODES = frozenset({"413"})

Operation = tuple[str, str]  # (метод, путь контракта без /api/v1)


@cache
def contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def operations(doc: dict[str, Any], *, prefix: str = "") -> dict[Operation, dict[str, Any]]:
    """``{(метод, путь без prefix): операция}``; маршруты вне prefix пропускаются."""
    result: dict[Operation, dict[str, Any]] = {}
    for path, item in doc.get("paths", {}).items():
        if prefix and not path.startswith(prefix):
            continue
        for method in HTTP_METHODS:
            if method in item:
                result[(method, path.removeprefix(prefix) or "/")] = item[method]
    return result


def _deref(doc: dict[str, Any], node: Any) -> Any:
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < _MAX_DEPTH:
        target: Any = doc
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
        seen += 1
    return node


def _drop_null(variants: list[Any]) -> list[Any]:
    return [v for v in variants if v != {"type": "null"}]


def normalize(doc: dict[str, Any], schema: Any, *, request: bool = False, depth: int = 0) -> Any:
    """Схема → сравнимая структура (см. описание модуля)."""
    schema = _deref(doc, schema)
    if not isinstance(schema, dict) or depth > _MAX_DEPTH:
        return schema
    for key in ("anyOf", "oneOf"):
        if key in schema:
            variants = [normalize(doc, v, request=request, depth=depth + 1) for v in schema[key]]
            unique = sorted({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in variants})
            if len(unique) == 1:
                return json.loads(unique[0])
            return {"anyOf": unique}
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return normalize(doc, schema["allOf"][0], request=request, depth=depth + 1)
    out: dict[str, Any] = {}
    kind = schema.get("type")
    if isinstance(kind, list):  # ["string", "null"] — та же запись, что anyOf
        kind = sorted(kind)
        if len(kind) == 1:
            kind = kind[0]
    if kind is not None:
        out["type"] = kind
    if "enum" in schema:
        out["enum"] = sorted(str(v) for v in schema["enum"])
    if "const" in schema:
        out["enum"] = [str(schema["const"])]
    if kind == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        props = {}
        for name, sub in schema.get("properties", {}).items():
            if request and name not in required:
                sub = _optional(doc, sub)
            props[name] = normalize(doc, sub, request=request, depth=depth + 1)
        out["properties"] = props
        out["required"] = sorted(required)
        if schema.get("additionalProperties") not in (None, True, False):
            out["additionalProperties"] = normalize(
                doc, schema["additionalProperties"], request=request, depth=depth + 1
            )
    if kind == "array":
        out["items"] = normalize(doc, schema.get("items", {}), request=request, depth=depth + 1)
    return out


def _optional(doc: dict[str, Any], schema: Any) -> Any:
    """Необязательное поле запроса: ``X | None`` → ``X``."""
    schema = _deref(doc, schema)
    if isinstance(schema, dict) and "anyOf" in schema:
        rest = _drop_null(schema["anyOf"])
        if len(rest) == 1:
            return rest[0]
        return {**schema, "anyOf": rest}
    return schema


def _request_schema(doc: dict[str, Any], op: dict[str, Any]) -> Any:
    body = _deref(doc, op.get("requestBody"))
    if not body:
        return None
    content = body.get("content", {}).get("application/json")
    return normalize(doc, content.get("schema"), request=True) if content else "не JSON"


def _response_schema(doc: dict[str, Any], op: dict[str, Any], code: str) -> Any:
    response = _deref(doc, op.get("responses", {}).get(code, {}))
    content = response.get("content", {})
    if "application/json" in content:
        return normalize(doc, content["application/json"].get("schema"))
    return None


def _params(doc: dict[str, Any], op: dict[str, Any]) -> list[tuple[str, str, bool]]:
    found = []
    for param in op.get("parameters", []):
        param = _deref(doc, param)
        if param.get("in") in ("path", "query"):
            found.append((param["in"], param["name"], bool(param.get("required"))))
    return sorted(found)


def _declared_codes(op: dict[str, Any]) -> set[str]:
    """Коды, которые объявил сам код эндпоинта; 422 FastAPI ставит сам — его не считаем."""
    codes = set(op.get("responses", {}))
    response_422 = op.get("responses", {}).get("422", {})
    schema = response_422.get("content", {}).get("application/json", {}).get("schema", {})
    if schema.get("$ref", "").endswith("/HTTPValidationError"):
        codes.discard("422")
    return codes


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def compare_operation(
    generated: dict[str, Any], gen_op: dict[str, Any], con_op: dict[str, Any]
) -> list[str]:
    """Расхождения одной операции; пустой список — реализация совпадает с контрактом."""
    doc = contract()
    issues: list[str] = []
    if gen_op.get("x-permission") != con_op.get("x-permission"):
        issues.append(
            f"право: реализация {gen_op.get('x-permission')!r}, "
            f"контракт {con_op.get('x-permission')!r}"
        )
    if bool(gen_op.get("x-step-up")) != bool(con_op.get("x-step-up")):
        issues.append(
            f"step-up: реализация {bool(gen_op.get('x-step-up'))}, "
            f"контракт {bool(con_op.get('x-step-up'))}"
        )
    gen_codes = _declared_codes(gen_op)
    con_codes = set(con_op.get("responses", {}))
    gen_ok = {c for c in gen_codes if c.startswith("2")}
    con_ok = {c for c in con_codes if c.startswith("2")}
    if gen_ok != con_ok:
        issues.append(f"успешные коды: реализация {sorted(gen_ok)}, контракт {sorted(con_ok)}")
    if extra := sorted(gen_codes - con_codes):
        issues.append(f"коды не из контракта: {extra}")
    if _params(generated, gen_op) != _params(doc, con_op):
        issues.append(
            f"параметры: реализация {_params(generated, gen_op)}, контракт {_params(doc, con_op)}"
        )
    gen_body, con_body = _request_schema(generated, gen_op), _request_schema(doc, con_op)
    if gen_body != con_body:
        issues.append(f"тело запроса: реализация {_show(gen_body)}, контракт {_show(con_body)}")
    for code in sorted(gen_ok & con_ok):
        gen_resp, con_resp = (
            _response_schema(generated, gen_op, code),
            _response_schema(doc, con_op, code),
        )
        if gen_resp != con_resp:
            issues.append(f"ответ {code}: реализация {_show(gen_resp)}, контракт {_show(con_resp)}")
    return issues


# --- Проверка живых ответов -----------------------------------------------------------------


@cache
def _registry() -> Registry:
    resource = Resource.from_contents(contract(), default_specification=DRAFT202012)
    return Registry().with_resource("urn:contract", resource)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


@cache
def _path_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns = []
    for path in contract()["paths"]:
        regex = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path))
        patterns.append((re.compile(f"^{regex}$"), path))
    # Буквальные сегменты раньше шаблонных: /me/sessions раньше /{id}
    patterns.sort(key=lambda item: item[1].count("{"))
    return patterns


def match_path(path: str) -> str | None:
    for pattern, template in _path_patterns():
        if pattern.match(path):
            return template
    return None


def check_response(
    method: str, url_path: str, status: int, content_type: str, body: Any
) -> list[str]:
    """Расхождения живого ответа с контрактом; пустой список — ответ соответствует."""
    if not url_path.startswith(API_PREFIX):
        return []
    path = url_path.removeprefix(API_PREFIX) or "/"
    template = match_path(path)
    if template is None:
        return []  # неизвестный путь: 404 проверяют тесты маршрутов
    op = contract()["paths"][template].get(method.lower())
    if op is None:
        return []
    where = f"{method.upper()} {template} → {status}"
    responses = op.get("responses", {})
    code = str(status)
    media = content_type.split(";")[0].strip()
    issues: list[str] = []
    if status >= 400 and media != PROBLEM_JSON:
        issues.append(f"{where}: ошибка не в формате {PROBLEM_JSON}, а {media or 'без тела'}")
    if code not in responses:
        if code in BODY_TRANSPORT_CODES and "requestBody" in op:
            return issues + _validate(where, "/components/schemas/Problem", body)
        return [f"{where}: код не объявлен в контракте (есть {sorted(responses)})"]
    pointer = f"/paths/{_escape(template)}/{method.lower()}/responses/{code}"
    response = responses[code]
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
        response = _deref(contract(), response)
    content = response.get("content", {})
    if not content:
        if body not in (None, b"", ""):
            issues.append(f"{where}: контракт не объявляет тело, а оно есть")
        return issues
    chosen = media if media in content else next(iter(content))
    if "schema" not in content[chosen]:
        return issues
    return issues + _validate(where, f"{pointer}/content/{_escape(chosen)}/schema", body)


def _validate(where: str, pointer: str, body: Any) -> list[str]:
    validator = Draft202012Validator({"$ref": f"urn:contract#{pointer}"}, registry=_registry())
    return [
        f"{where}: /{'/'.join(str(p) for p in error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    ]
