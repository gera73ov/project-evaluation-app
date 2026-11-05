"""API-002 · проверка контракта contracts/openapi.yaml (SPEC 15, SEC-AUTHZ-04).

Тест не проверяет сервер (это API-003 и тесты треков), а держит контракт согласованным:
документ — корректный OpenAPI 3.1, каждая строка таблицы SPEC 15.2 есть среди операций,
у каждой операции есть право, ссылки на SPEC и коды ошибок из contracts/errors.yaml,
десятичные значения передаются строками, а деньги лежат только в схемах *Money.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
OPENAPI = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"))
ERROR_CODES = {
    item["code"]
    for item in yaml.safe_load((CONTRACTS / "errors.yaml").read_text(encoding="utf-8"))["errors"]
}
PERMISSIONS_FILE = CONTRACTS / "permissions.yaml"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
METHOD_RE = r"(?:GET|POST|PUT|PATCH|DELETE)"
# Особые значения x-permission: операции без входа и операции для любого вошедшего.
PSEUDO_PERMISSIONS = {"public", "authenticated"}
# Схемы с деньгами вне *Money и почему это не нарушает SEC-AUTHZ-04.
MONEY_OUTSIDE_MONEY_SCHEMAS = {
    "Rate": "вложена только в ProjectMoney",
    "ProjectOutcomePut": "тело запроса; contract_amount принимается только с money.write и TOTP",
    "PortfolioSummary": "весь эндпоинт закрыт правом portfolio.read и TOTP (FR-PORT-02)",
}


def _operations() -> list[tuple[str, str, dict]]:
    return [
        (method, path, op)
        for path, ops in OPENAPI["paths"].items()
        for method, op in ops.items()
        if method in HTTP_METHODS
    ]


OPERATIONS = _operations()


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip("/"))


def _spec_15_2_rows() -> list[tuple[str, str]]:
    """Строки «метод путь» из таблицы SPEC 15.2 с раскрытием сокращений.

    В ячейке через запятую идут пути; «GET/POST» — несколько методов; кусок без метода
    наследует методы предыдущего; «/reset-totp» (один сегмент) заменяет последний сегмент
    предыдущего пути; «.../export» дописывается к предыдущему пути; скобки — пояснения.
    """
    spec = (ROOT / "docs" / "spec" / "SPEC.md").read_text(encoding="utf-8")
    section = spec[spec.index("### 15.2.") : spec.index("### 15.3.")]
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        if not re.match(r"^\|\s*" + METHOD_RE, line):
            continue
        cell = re.sub(r"\([^)]*\)", "", line.split("|")[1]).replace("`", "")
        methods: list[str] = []
        last = ""
        for piece in (part.strip() for part in cell.split(",") if part.strip()):
            match = re.match(rf"^({METHOD_RE}(?:/{METHOD_RE})*)\s+(\S+)", piece)
            if match:
                methods = match.group(1).split("/")
                path = match.group(2)
            else:
                path = piece.split()[0]
                if path.count("/") == 1:
                    path = re.sub(r"/[^/{}]*$", "", last) + path
            if path.startswith("..."):
                path = last + path[3:]
            last = path
            rows += [(method, path.split("?")[0]) for method in methods]
    return rows


def test_document_is_valid_openapi_3_1() -> None:
    assert OPENAPI["openapi"].startswith("3.1.")
    validate(OPENAPI)


def test_servers_prefix_is_api_v1() -> None:
    assert [server["url"] for server in OPENAPI["servers"]] == ["/api/v1"]


@pytest.mark.spec("15.2")
def test_every_spec_endpoint_has_operation() -> None:
    have = {(method.upper(), _norm(path)) for method, path, _ in OPERATIONS}
    rows = _spec_15_2_rows()
    assert len(rows) > 100, "таблица 15.2 разобрана не полностью"
    missing = [row for row in rows if (row[0], _norm(row[1])) not in have]
    assert not missing, f"нет операций для строк SPEC 15.2: {missing}"


def test_operation_ids_are_unique() -> None:
    ids = [op["operationId"] for _, _, op in OPERATIONS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("method", "path", "op"), OPERATIONS, ids=[f"{m.upper()} {p}" for m, p, _ in OPERATIONS]
)
def test_operation_is_annotated(method: str, path: str, op: dict) -> None:
    assert op.get("summary"), "нет summary"
    assert op.get("x-permission"), "нет x-permission"
    assert op.get("x-spec"), "нет x-spec"
    codes = op.get("x-error-codes", [])
    unknown = set(codes) - ERROR_CODES
    assert not unknown, f"коды не из contracts/errors.yaml: {unknown}"
    # public и token.* (вход по одноразовому токену) — без сессии, 401 не возвращают.
    permission = op["x-permission"]
    if permission != "public" and not str(permission).startswith("token."):
        assert "UNAUTHENTICATED" in codes, "закрытая операция без 401"


@pytest.mark.spec("SEC-AUTHZ-01")
def test_permissions_exist_in_matrix() -> None:
    data = yaml.safe_load(PERMISSIONS_FILE.read_text(encoding="utf-8"))["permissions"]
    known = set(data) | PSEUDO_PERMISSIONS
    used = set()
    for _, _, op in OPERATIONS:
        value = op["x-permission"]
        used |= set(value if isinstance(value, list) else [value])
    assert not used - known, f"права не из матрицы: {sorted(used - known)}"


def test_decimals_are_strings() -> None:
    """Десятичные числа передаются строками (contracts/api-conventions.md 2.1)."""
    assert '"type": "number"' not in json.dumps(OPENAPI)


@pytest.mark.spec("SEC-AUTHZ-04")
def test_money_lives_only_in_money_schemas() -> None:
    schemas = OPENAPI["components"]["schemas"]
    offenders = {
        name
        for name, schema in schemas.items()
        if "#/components/schemas/MoneyString" in json.dumps(schema)
        and "Money" not in name
        and name not in MONEY_OUTSIDE_MONEY_SCHEMAS
    }
    assert not offenders, f"деньги вне схем *Money: {sorted(offenders)}"
