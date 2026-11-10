"""SEC-011: условия оповещений ИБ и ключи писем (SEC-AUTH-07, contracts/audit-events.yaml)."""

from __future__ import annotations

from typing import Any

import pytest

from estimator.notifications.mail.render import ALERT_LABELS
from estimator.security.alerts import rules
from estimator.security.audit.catalog import EVENTS, SECURITY_ALERTS

pytestmark = pytest.mark.spec("SEC-AUTH-07")


@pytest.mark.parametrize(
    ("event", "details", "expected"),
    [
        ("auth.password.reset_issued", {"target_roles": ["admin"]}, True),
        ("auth.password.reset_issued", {"target_roles": ["superadmin"]}, True),
        ("auth.password.reset_issued", {"target_roles": ["moderator"]}, False),
        ("users.roles.changed", {"added": ["security_auditor"], "removed": []}, True),
        ("users.roles.changed", {"added": [], "removed": ["admin"]}, True),
        ("users.roles.changed", {"added": ["presale"], "removed": ["moderator"]}, False),
        ("system.settings.changed", {"section": "smtp", "changes": {}}, True),
        ("system.settings.changed", {"section": "security.admin_networks", "changes": {}}, True),
        ("system.settings.changed", {"section": "digest", "changes": {}}, False),
        ("system.settings.changed",
         {"section": "security.mfa_policy", "changes": {"admin": ["required", "optional"]}}, True),
        ("system.settings.changed",
         {"section": "security.mfa_policy", "changes": {"user": ["optional", "required"]}}, False),
        ("system.settings.changed",
         {"section": "security.mfa_policy",
          "changes": {"section": [{"admin": "required"}, {"admin": "optional"}]}}, True),
        ("system.settings.changed",
         {"section": "security.mfa_policy", "changes": "не словарь"}, False),
        ("system.auth_mode.switched", {"dry_run": True}, False),
        ("system.auth_mode.switched", {"dry_run": False}, True),
        ("system.audit_chain.verified", {"ok": False}, True),
        ("system.audit_chain.verified", {"ok": True}, False),
        ("auth.logout", {}, False),
    ],
)  # fmt: skip
def test_conditions(event: str, details: dict[str, Any], expected: bool) -> None:
    assert rules.triggered(event, details) is expected


def test_conditional_events_of_contract_are_covered() -> None:
    conditional = {name for name, spec in EVENTS.items() if spec.alert == "conditional"}
    covered = {"auth.password.reset_issued", "users.roles.changed", "system.settings.changed",
               "system.auth_mode.switched", "system.audit_chain.verified"}  # fmt: skip
    assert conditional <= covered


@pytest.mark.parametrize(
    ("event", "details", "key"),
    [
        ("system.settings.changed", {"section": "smtp"}, "smtp_changed"),
        ("system.settings.changed", {"section": "security.admin_networks"},
         "admin_networks_changed"),
        ("system.settings.changed", {"section": "security.mfa_policy"},
         "mfa_requirement_disabled"),
        ("users.roles.changed", {"added": ["security_auditor"]}, "security_auditor_role"),
        ("users.roles.changed", {"removed": ["admin"]}, "privileged_account_changed"),
        ("auth.mfa.reset", {}, "privileged_totp_reset"),
        ("security.login_failures_burst", {}, "login_failures_burst"),
        ("system.audit_chain.verified", {"ok": False}, "audit_chain_broken"),
        ("auth.logout", {}, "auth.logout"),
    ],
)  # fmt: skip
def test_alert_key(event: str, details: dict[str, Any], key: str) -> None:
    assert rules.alert_key(event, details) == key


def test_every_alert_key_has_label_and_source_event() -> None:
    assert set(ALERT_LABELS) == set(SECURITY_ALERTS)
    produced = {rules.alert_key(e, {}) for e in set(SECURITY_ALERTS.values())}
    produced |= {rules.alert_key("system.settings.changed", {"section": s})
                 for s in rules.SETTINGS_ALERT_SECTIONS}  # fmt: skip
    produced.add(rules.alert_key("users.roles.changed", {"added": ["security_auditor"]}))
    assert set(SECURITY_ALERTS) <= produced
