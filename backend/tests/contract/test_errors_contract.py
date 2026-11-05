"""API-001 · проверка словаря ошибок contracts/errors.yaml (SPEC 15.1, 15.3, SEC-WEB-09).

Тест держит словарь в согласованном виде: коды уникальны и стабильны по форме, у каждого есть
HTTP-статус, тип проблемы, текст для пользователя и ссылка на SPEC, а все коды, которые SPEC и
PLAN.md (раздел 6) называют явно, присутствуют со своими статусами.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
ERRORS = yaml.safe_load((CONTRACTS / "errors.yaml").read_text(encoding="utf-8"))["errors"]
BY_CODE = {item["code"]: item for item in ERRORS}

# Коды, которые SPEC называет явно, со статусами из SPEC (15.3, BR-ROLE-03/07, FR-2FA-05,
# FR-TREE-31, BR-TREE-06) и PLAN.md раздел 6 (словарь ошибок).
SPEC_CODES = {
    "FIELD_CONFLICT": 409,
    "CELL_LOCKED": 423,
    "NODES_LIMIT": 409,
    "DEPTH_LIMIT": 422,
    "NODE_HAS_CHILDREN": 422,
    "VALUE_OUT_OF_RANGE": 422,
    "LAST_MODERATOR": 409,
    "LAST_SUPERADMIN": 409,
    "TOTP_REQUIRED": 403,
}

# Статусы, которые требует SPEC: для каждого должен быть хотя бы один код.
SPEC_STATUSES = {
    401: "15.1, 17.3: повтор старого cookie",
    403: "SEC-AUTHZ-05, TC-SEC-08",
    404: "SEC-AUTHZ-03",
    409: "FR-PORT-03, BR-ROLE-03",
    410: "ARCH-02 (слишком старая версия)",
    422: "15.3",
    423: "FR-TREE-31",
    429: "15.2 POST /remind, SEC-WEB-07",
    500: "SEC-WEB-09",
}

REQUIRED_FIELDS = ("code", "status", "type", "title", "when", "user_message", "spec")


def test_codes_are_unique_and_upper_snake() -> None:
    codes = [item["code"] for item in ERRORS]
    assert len(codes) == len(set(codes)), "коды ошибок повторяются"
    for code in codes:
        assert re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*", code), code


def test_types_are_unique_kebab_slugs() -> None:
    types = [item["type"] for item in ERRORS]
    assert len(types) == len(set(types)), "типы проблем повторяются"
    for slug in types:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug), slug


@pytest.mark.parametrize("item", ERRORS, ids=lambda item: item["code"])
def test_entry_is_complete(item: dict) -> None:
    for field in REQUIRED_FIELDS:
        assert item.get(field), f"{item['code']}: нет поля {field}"
    assert isinstance(item["status"], int)
    assert 400 <= item["status"] <= 599
    assert isinstance(item["spec"], list)
    assert all(isinstance(ref, str | float | int) for ref in item["spec"])
    extensions = item.get("extensions", {})
    reserved = {"type", "title", "status", "code", "detail", "error_id", "instance"}
    assert not reserved & set(extensions), f"{item['code']}: расширение перекрывает поле RFC 9457"


@pytest.mark.spec("15.3")
@pytest.mark.parametrize(("code", "status"), sorted(SPEC_CODES.items()))
def test_spec_codes_present_with_spec_status(code: str, status: int) -> None:
    assert code in BY_CODE, f"нет кода {code}, названного в SPEC"
    assert BY_CODE[code]["status"] == status


@pytest.mark.parametrize("status", sorted(SPEC_STATUSES))
def test_spec_statuses_covered(status: int) -> None:
    assert any(item["status"] == status for item in ERRORS), SPEC_STATUSES[status]


@pytest.mark.spec("FR-AUTH-AD-13")
def test_login_texts_are_verbatim_from_spec() -> None:
    login = BY_CODE["LOGIN_FAILED"]
    assert login["verbatim"] is True
    assert login["user_message"] == "Неверный логин или пароль"
    assert login["user_message_ad"] == (
        "Неверный логин или пароль. Если уверены в пароле — обратитесь к администратору"
    )
    assert BY_CODE["LOGIN_LOCKED"]["user_message"] == (
        "Слишком много попыток, повторите через 15 минут"
    )
    assert BY_CODE["AUTH_SERVICE_UNAVAILABLE"]["user_message"] == (
        "Сервис аутентификации временно недоступен"
    )


@pytest.mark.spec("FR-AUTH-AD-13")
def test_login_failures_do_not_reveal_reason() -> None:
    """Ответ на отказ входа не содержит полей, по которым можно узнать причину (R-04)."""
    for code in ("LOGIN_FAILED", "LOGIN_LOCKED"):
        extensions = set(BY_CODE[code].get("extensions", {}))
        assert not extensions & {"reason", "attempts_left", "user_exists"}, code


@pytest.mark.spec("SEC-WEB-09")
def test_internal_error_has_no_extensions() -> None:
    assert BY_CODE["INTERNAL_ERROR"]["status"] == 500
    assert not BY_CODE["INTERNAL_ERROR"].get("extensions")


def test_rate_limit_codes_carry_retry_after() -> None:
    for item in ERRORS:
        if item["status"] == 429 and item["code"] != "LOGIN_LOCKED":
            assert "retry_after" in item.get("extensions", {}), item["code"]
