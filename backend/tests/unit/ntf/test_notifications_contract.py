"""NTF-001: contracts/notifications.yaml покрывает FR-NOTIF-01..03 и строки 3.4 об уведомлениях."""

from __future__ import annotations

import pytest

from tests.unit._contracts import load_yaml

pytestmark = [pytest.mark.spec("FR-NOTIF-01"), pytest.mark.spec("FR-NOTIF-02")]

N = load_yaml("notifications.yaml")
P = load_yaml("permissions.yaml")
KINDS: dict = N["kinds"]
EMAILS: dict = N["emails"]
STATUSES = ["preparation", "estimation", "consolidation", "completed", "archived"]


def test_fr_notif_01_items_present():
    assert {
        "question_to_me", "answer_to_my_question", "moderator_change", "branch_back_to_draft",
        "assigned_to_project", "member_replaced", "question_redirected", "member_blocked",
        "presale_head_joined", "support_session_opened", "project_without_moderator",
    } <= set(KINDS)  # fmt: skip


def test_fr_notif_02_emails_present():
    assert {"digest", "questions_batch", "assigned_to_project", "password_setup",
            "password_reset", "new_device_login", "security_alert"} <= set(EMAILS)  # fmt: skip
    assert EMAILS["questions_batch"]["window_minutes"] == 15
    assert EMAILS["digest"]["opt_out"] == "users.notify_digest"
    assert EMAILS["questions_batch"]["opt_out"] == "users.notify_questions"
    for name in ("assigned_to_project", "password_setup", "password_reset", "new_device_login",
                 "security_alert"):  # fmt: skip
        assert EMAILS[name]["opt_out"] is None, name


def test_classes_follow_matrix_3_4():
    rows = {r["id"]: r for r in P["matrix_3_4"]}
    for name, cls in N["classes"].items():
        row = rows[cls["matrix_row"]]
        for st in STATUSES:
            spec_cell = row["statuses"][st]
            mine = cls["statuses"][st]
            if spec_cell["effect"] == "deny":
                assert mine == "deny", (name, st)
            elif "customer_questions_only" in spec_cell.get("flags", []):
                assert mine == "customer_questions_only", (name, st)
            else:
                assert mine == "allow", (name, st)


def test_kinds_are_well_formed():
    for name, k in KINDS.items():
        assert k["class"] in N["classes"], name
        assert isinstance(k["cq_related"], bool), name
        assert k["email"] is None or k["email"] in EMAILS, name
        assert isinstance(k["store"], bool), name
        assert set(k["payload"]) & {"body", "text", "title", "rate", "cost", "money"} == set()


def test_emails_carry_no_content():
    """FR-NOTIF-03: в письмах только название проекта, счётчики и ссылка."""
    banned = {"node", "node_title", "title", "body", "text", "message", "rate", "cost", "money",
              "estimate", "e", "p80"}  # fmt: skip
    for name, e in EMAILS.items():
        assert set(e["email_fields"]) & banned == set(), name
