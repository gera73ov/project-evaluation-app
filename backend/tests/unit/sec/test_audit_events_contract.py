"""SEC-002: contracts/audit-events.yaml покрывает SEC-AUD-01/02 и SEC-AUTH-07."""

from __future__ import annotations

import re

import pytest

from tests.unit._contracts import load_yaml, spec_table, spec_text

pytestmark = [pytest.mark.spec("SEC-AUD-01"), pytest.mark.spec("SEC-AUD-02")]

A = load_yaml("audit-events.yaml")
EVENTS: dict = A["events"]


def test_record_fields_are_sec_aud_02():
    assert list(A["record"]) == [
        "time", "type", "result", "user_id", "login", "ip", "user_agent", "session_hash",
        "object_type", "object_id", "details", "prev_hash", "hash",
    ]  # fmt: skip
    assert set(A["results"]) == {"success", "failure", "denied"}


def test_every_sec_aud_01_category_has_events():
    titles = {row[0] for row in spec_table("**SEC-AUD-01.**")}
    assert titles == {c["title"] for c in A["categories"].values()}
    used = {e["category"] for e in EVENTS.values()}
    assert used == set(A["categories"])


def test_admin_sees_only_two_categories():
    seen = {k for k, c in A["categories"].items() if "admin" in c["visible_to"]}
    assert seen == {"dictionaries", "users_roles"}


def test_login_failure_reasons():
    reasons = set(A["login_failure_reasons"])
    # SEC-AUD-01: нет пользователя, неверный пароль, заблокирован, не в группе AD,
    # неверный TOTP, пустой пароль; 17.2: ad_account_disabled, ad_not_in_group
    assert {"user_not_found", "wrong_password", "user_blocked", "ad_not_in_group",
            "invalid_totp", "empty_credentials", "ad_account_disabled"} <= reasons  # fmt: skip
    gherkin = set(re.findall(r"login\.failed с причиной (\w+)", spec_text()))
    assert gherkin <= reasons


def test_details_have_no_secrets_money_or_content():
    forbidden = set(A["forbidden_detail_keys"])
    for code, ev in EVENTS.items():
        assert set(ev["details"]) & forbidden == set(), code
        assert set(ev) <= {"category", "title", "spec", "object", "details", "alert"}, code
        assert ev["object"] is None or ev["object"] in A["object_types"], code


def test_security_alerts_map_to_alerting_events():
    for name, code in A["security_alerts"].items():
        assert "alert" in EVENTS[code], name


def test_cli_commands_cover_18_2():
    cmd = EVENTS["system.cli.executed"]["details"]["command"]
    for name in ("migrate", "create-superadmin", "issue-activation", "reset-superadmin",
                 "auth-mode", "rotate-key", "audit verify", "audit purge", "project purge",
                 "seed-demo"):  # fmt: skip
        assert name in cmd
