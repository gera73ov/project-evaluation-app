"""API-004 · реализация совпадает с contracts/openapi.yaml (SPEC 15.1, 15.2).

OpenAPI, который строит FastAPI, сверяется с контрактом оператор за оператором
(:func:`tests.contract.openapi_impl.compare_operation`). Падает CI, если:

* у реализации есть операция, которой нет в контракте;
* право, успешные коды, параметры, схема тела запроса или успешного ответа расходятся с
  контрактом, и расхождение не записано в :data:`KNOWN_GAPS`;
* расхождение из :data:`KNOWN_GAPS` уже исправлено, а запись осталась (список только сокращается).

Отчёт «реализовано / не реализовано» пишется в Markdown по пути из ``API_CONTRACT_REPORT``;
CI публикует его артефактом.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from estimator import health
from estimator.config import Settings
from estimator.main import create_app
from tests.contract.openapi_impl import (
    API_PREFIX,
    check_response,
    compare_operation,
    contract,
    operations,
)

#: Известные расхождения: операция → виды расхождений (текст до первого двоеточия).
#: Каждая запись — долг трека-владельца эндпоинта; исправил — удали запись, иначе тест упадёт.
#: Эндпоинты AUTH (трек 3) пока отдают словари без ``response_model``, поэтому схема успешного
#: ответа в сгенерированном OpenAPI пустая.
KNOWN_GAPS: dict[tuple[str, str], set[str]] = {
    ("post", "/auth/login"): {"ответ 200"},
    ("get", "/auth/options"): {"ответ 200"},
    ("post", "/auth/totp"): {"ответ 200"},
    ("post", "/auth/totp/enroll"): {"ответ 200"},
    ("post", "/auth/totp/enroll/confirm"): {"ответ 200"},
    ("post", "/auth/step-up"): {"ответ 200"},
    ("get", "/me"): {"ответ 200"},
    ("patch", "/me"): {"ответ 200"},
    ("get", "/me/sessions"): {"ответ 200"},
    ("post", "/me/totp"): {"ответ 200"},
    ("post", "/me/backup-codes"): {"ответ 200"},
    ("get", "/me/notification-settings"): {"ответ 200"},
    ("put", "/me/notification-settings"): {"ответ 200"},
}


def _generated() -> dict[str, Any]:
    app = create_app(Settings(app_env="test"), probes=health.Probes())
    return app.openapi()


GENERATED = _generated()
IMPLEMENTED = operations(GENERATED, prefix=API_PREFIX)
CONTRACT_OPS = operations(contract())


def _kinds(issues: list[str]) -> set[str]:
    return {issue.split(":", 1)[0] for issue in issues}


def _issues(op: tuple[str, str]) -> list[str]:
    return compare_operation(GENERATED, IMPLEMENTED[op], CONTRACT_OPS[op])


def _id(op: tuple[str, str]) -> str:
    return f"{op[0].upper()} {op[1]}"


def test_implementation_has_operations() -> None:
    assert IMPLEMENTED, "реализация не отдаёт ни одной операции /api/v1"


@pytest.mark.parametrize("op", sorted(IMPLEMENTED), ids=_id)
def test_operation_matches_contract(op: tuple[str, str]) -> None:
    assert op in CONTRACT_OPS, f"{_id(op)} нет в contracts/openapi.yaml: сначала контракт (CR)"
    issues = _issues(op)
    known = KNOWN_GAPS.get(op, set())
    new = [issue for issue in issues if issue.split(":", 1)[0] not in known]
    assert not new, "реализация расходится с контрактом:\n" + "\n".join(new)
    fixed = known - _kinds(issues)
    assert not fixed, f"расхождения {sorted(fixed)} исправлены — убери их из KNOWN_GAPS"


def test_known_gaps_point_to_implemented_operations() -> None:
    stale = sorted(_id(op) for op in KNOWN_GAPS if op not in IMPLEMENTED)
    assert not stale, f"KNOWN_GAPS ссылается на нереализованные операции: {stale}"


def test_comparison_catches_drift() -> None:
    """Самопроверка: подмена права и схемы ответа даёт расхождения."""
    op = ("get", "/auth/options")
    con_op = CONTRACT_OPS[op]
    drifted = {**con_op, "x-permission": "project.read", "responses": {"201": {}}}
    kinds = _kinds(compare_operation(contract(), drifted, con_op))
    assert {"право", "успешные коды"} <= kinds
    assert compare_operation(contract(), con_op, con_op) == []


def render_report() -> str:
    rows = []
    for op in sorted(CONTRACT_OPS, key=lambda o: (o[1], o[0])):
        if op not in IMPLEMENTED:
            state, notes = "не реализовано", ""
        else:
            issues = _issues(op)
            state = "реализовано" if not issues else "реализовано с расхождениями"
            notes = "; ".join(sorted(_kinds(issues)))
        rows.append(f"| `{op[0].upper()}` | `{op[1]}` | {state} | {notes} |")
    done = sum(1 for op in CONTRACT_OPS if op in IMPLEMENTED)
    head = [
        "# Реализация API против contracts/openapi.yaml",
        "",
        f"Реализовано {done} из {len(CONTRACT_OPS)} операций контракта.",
        "",
        "| Метод | Путь | Состояние | Расхождения |",
        "|---|---|---|---|",
    ]
    return "\n".join(head + rows) + "\n"


def test_report() -> None:
    report = render_report()
    assert "Реализовано" in report
    target = os.environ.get("API_CONTRACT_REPORT")
    if target:
        Path(target).write_text(report, encoding="utf-8")


def test_live_check_catches_drift() -> None:
    """Самопроверка проверки живых ответов: чужой код, лишнее поле, не problem+json."""
    url, js = "/api/v1/auth/options", "application/json"
    assert check_response("GET", url, 200, js, {"auth_mode": "app"}) == []
    assert check_response("GET", url, 201, js, {})
    bad = check_response("GET", url, 200, js, {"auth_mode": "x"})
    assert bad
    assert "/auth_mode" in bad[0]
    plain = check_response("GET", url, 429, js, {})
    assert any("problem+json" in issue for issue in plain)
    assert check_response("GET", "/health/live", 200, "application/json", {}) == []
