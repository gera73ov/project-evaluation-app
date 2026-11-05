"""SEC-004: каталог событий в коде совпадает с contracts/audit-events.yaml; проверки details."""

from __future__ import annotations

import pytest

from estimator.security.audit import AuditError, build_details
from estimator.security.audit.catalog import (
    ACTORS,
    COMMON_DETAILS,
    CONTRACT_VERSION,
    EVENTS,
    FORBIDDEN_DETAIL_KEYS,
    LOGIN_FAILURE_REASONS,
    OBJECT_TYPES,
    SECURITY_ALERTS,
)
from estimator.security.audit.runs import AUDITED_COMMANDS
from tests.unit._contracts import load_yaml

pytestmark = pytest.mark.spec("SEC-AUD-01")

Y = load_yaml("audit-events.yaml")


def test_catalog_matches_contract() -> None:
    assert Y["version"] == CONTRACT_VERSION
    assert set(Y["events"]) == set(EVENTS)
    for name, e in Y["events"].items():
        spec = EVENTS[name]
        assert spec.category == e["category"], name
        assert spec.object_type == e.get("object"), name
        assert spec.details == frozenset((e.get("details") or {}).keys()), name
        alert = e.get("alert")
        expected = None if not alert else ("always" if alert == "always" else "conditional")
        assert spec.alert == expected, name
    assert frozenset(Y["common_details"]) == COMMON_DETAILS
    assert frozenset(Y["forbidden_detail_keys"]) == FORBIDDEN_DETAIL_KEYS
    assert frozenset(Y["object_types"]) == OBJECT_TYPES
    assert frozenset(Y["actors"]) == ACTORS
    assert frozenset(Y["login_failure_reasons"]) == LOGIN_FAILURE_REASONS
    assert dict(Y["security_alerts"]) == SECURITY_ALERTS


def test_audited_commands_match_contract() -> None:
    enum = Y["events"]["system.cli.executed"]["details"]["command"]
    listed = {c.strip() for c in enum.removeprefix("enum[").removesuffix("]").split(",")}
    assert listed == AUDITED_COMMANDS


def test_build_details_accepts_schema_and_common_keys() -> None:
    data = build_details(
        "auth.login.failed",
        {"reason": "wrong_password", "method": "local", "step": "password"},
        actor="anonymous",
    )
    assert data == {
        "reason": "wrong_password",
        "method": "local",
        "step": "password",
        "actor": "anonymous",
    }
    assert "actor" not in build_details("auth.logout", {})
    assert build_details("auth.logout", {}, os_user="ops", project_id="p")["project_id"] == "p"


@pytest.mark.spec("SEC-AUTH-04")
def test_build_details_rejects_unknown_forbidden_and_scrubs_nested() -> None:
    with pytest.raises(AuditError, match="неизвестное событие"):
        build_details("nope", {})
    with pytest.raises(AuditError, match="вне каталога"):
        build_details("auth.logout", {"reason": "x"})
    with pytest.raises(AuditError, match="actor"):
        build_details("auth.logout", {}, actor="robot")
    data = build_details(
        "system.cli.executed",
        {"command": "rotate-key", "args": {"login": "sa", "password": "p", "nested": {"token": 1}},
         "host": "h", "exit_code": 0},
        actor="cli",
    )  # fmt: skip
    assert data["args"] == {"login": "sa", "password": "***", "nested": {"token": "***"}}


def test_forbidden_key_in_schema_is_allowed_only_where_declared() -> None:
    """Ключ из forbidden_detail_keys, объявленный в схеме события, не блокирует запись."""
    overlap = {n: s.details & FORBIDDEN_DETAIL_KEYS for n, s in EVENTS.items()}
    for name, keys in overlap.items():
        for key in keys:
            build_details(name, {key: "x"})
