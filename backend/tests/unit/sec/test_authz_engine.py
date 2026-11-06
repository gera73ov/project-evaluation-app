"""SEC-005: движок прав по записям contracts/permissions.yaml (SEC-AUTHZ-01…05, 3.3, 3.4)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from estimator.security.authz.catalog import STATUSES, load_catalog
from estimator.security.authz.engine import (
    Access,
    AccessDenied,
    Membership,
    Subject,
    Target,
    decide,
    decide_any,
)

pytestmark = [pytest.mark.spec("SEC-AUTHZ-02"), pytest.mark.spec("SEC-AUTHZ-03")]

CAT = load_catalog()
ME = uuid.uuid4()
OTHER = uuid.uuid4()
PROJECT = uuid.uuid4()
BACKEND = uuid.uuid4()
FRONTEND = uuid.uuid4()

MEMBERS = {
    "project_moderator": Membership("moderator"),
    "expert": Membership("expert", BACKEND),
    "reviewer": Membership("expert", BACKEND, is_reviewer=True),
    "project_presale": Membership("presale"),
}


def subj(*roles: str, members: tuple[str, ...] = (), **kw: Any) -> Subject:
    kw.setdefault("mfa_passed", True)
    return Subject(
        user_id=ME,
        roles=frozenset(roles),
        memberships=tuple(MEMBERS[m] for m in members),
        **kw,
    )


def proj(status: str = "estimation", **kw: Any) -> Target:
    return Target(project_id=PROJECT, project_status=status, **kw)


def code_of(code: str, subject: Subject, target: Target) -> str:
    try:
        decide(CAT, subject, code, target)
    except AccessDenied as exc:
        return exc.code
    return "OK"


# --- SEC-AUTHZ-05: таблица примеров (authz_examples) ---------------------------------------

EXPERT = subj(members=("expert",))
MODERATOR = subj("moderator", members=("project_moderator",))
PRESALE = subj("presale", members=("project_presale",))
ADMIN = subj("admin")
ADMIN_SUPPORT = subj("admin", support=True)
HEAD = subj("presale_head")
AUDITOR = subj("security_auditor")
SUPER = subj("superadmin")
STRANGER = subj()

LEAF_BACKEND = proj(disciplines=frozenset({BACKEND}))
LEAF_FRONTEND = proj(disciplines=frozenset({FRONTEND}))
CROSS = proj(disciplines=frozenset({BACKEND, FRONTEND}))


@pytest.mark.spec("SEC-AUTHZ-05")
@pytest.mark.parametrize(
    ("who", "code", "target", "expect"),
    [
        (EXPERT, "tree.write", LEAF_BACKEND, "OK"),
        (EXPERT, "tree.write", LEAF_FRONTEND, "FORBIDDEN"),
        (EXPERT, "tree.move.cross_branch", CROSS, "FORBIDDEN"),
        (EXPERT, "tree.write", CROSS, "FORBIDDEN"),
        (EXPERT, "money.read", proj(), "FORBIDDEN"),
        (EXPERT, "notes.read", proj(), "FORBIDDEN"),
        (STRANGER, "tree.read", proj(), "NOT_FOUND"),
        (PRESALE, "tree.write", LEAF_BACKEND, "FORBIDDEN"),
        (ADMIN, "tree.read", proj(), "NOT_FOUND"),
        (ADMIN_SUPPORT, "money.read", proj(), "FORBIDDEN"),
        (ADMIN_SUPPORT, "tree.write", LEAF_BACKEND, "FORBIDDEN"),
        (ADMIN_SUPPORT, "tree.read", proj(), "OK"),
        (HEAD, "money.read", proj(), "OK"),
        (HEAD, "tree.write", LEAF_BACKEND, "FORBIDDEN"),
        (AUDITOR, "tree.read", proj(), "NOT_FOUND"),
        (SUPER, "tree.read", proj(), "NOT_FOUND"),
        (MODERATOR, "tree.write", LEAF_FRONTEND, "OK"),
        (subj(members=("project_moderator",), mfa_passed=False), "money.read", proj(),
         "TOTP_REQUIRED"),
        (HEAD, "project.join_as_moderator", proj("archived"), "PROJECT_STATUS_CONFLICT"),
        (HEAD, "project.join_as_moderator", proj("completed"), "OK"),
        (HEAD, "notes.write", proj(), "FORBIDDEN"),
        (HEAD, "team.write", proj(), "FORBIDDEN"),
        (EXPERT, "thread.resolve", proj(author_id=ME), "OK"),
        (EXPERT, "thread.resolve", proj(author_id=OTHER), "FORBIDDEN"),
        (EXPERT, "thread.resolve", proj(author_id=OTHER, addressees=frozenset({ME})), "OK"),
        (EXPERT, "cq.close", proj(author_id=ME), "OK"),
        (EXPERT, "cq.close", proj(author_id=OTHER), "FORBIDDEN"),
        (subj(members=("project_moderator",), facts={"auth.mode": "ad"}), "project.ad_search",
         proj(), "OK"),
        (subj(members=("project_moderator",)), "project.ad_search", proj(), "FORBIDDEN"),
        (EXPERT, "project.ad_search", proj(), "FORBIDDEN"),
    ],
)  # fmt: skip
def test_authz_examples(who: Subject, code: str, target: Target, expect: str) -> None:
    assert code_of(code, who, target) == expect


def test_authz_examples_cover_contract_table() -> None:
    import yaml

    from estimator.security.authz.catalog import _path

    examples = yaml.safe_load(_path().read_text(encoding="utf-8"))["authz_examples"]
    assert len(examples) == 23  # все строки SEC-AUTHZ-05 разобраны в параметрах выше


# --- Матрица 3.4: каждая строка × статус × субъект ----------------------------------------


def _gate_cases() -> list[tuple[str, str, str, str]]:
    cases = []
    for gate in CAT.gates:
        if gate.evaluated_on or gate.key == "project.visibility":
            continue
        for subject in sorted(gate.applies_to):
            if subject not in MEMBERS:
                continue
            for code in sorted(gate.permissions):
                for status in STATUSES:
                    cases.append((gate.id, subject, code, status))
    return cases


@pytest.mark.spec("3.4")
@pytest.mark.spec("TC-SEC-06")
@pytest.mark.parametrize(("gate_id", "member", "code", "status"), _gate_cases())
def test_status_gates(gate_id: str, member: str, code: str, status: str) -> None:
    subject = subj("moderator", members=(member,), step_up_active=True,
                   facts={"auth.mode": "ad"})  # fmt: skip
    target = proj(status, disciplines=frozenset({BACKEND}), author_id=ME,
                  attrs={"cq_status": "new"}, kind="document")  # fmt: skip
    result = code_of(code, subject, target)
    if result == "FORBIDDEN":  # роль права не даёт — строка 3.4 к ней не относится
        return
    visible = status != "preparation" or member == "project_moderator"
    allowed = all(
        g.allows(member, status)
        for g in CAT.gates_for(code)
        if g.covers(member) and g.evaluated_on is None
    )
    if not visible:
        assert result == "NOT_FOUND", gate_id
    elif allowed:
        assert result == "OK", gate_id
    else:
        assert result == "PROJECT_STATUS_CONFLICT", gate_id


@pytest.mark.spec("3.4")
@pytest.mark.parametrize("status", STATUSES)
def test_copy_source_project_status(status: str) -> None:
    """M3.4-09: источник копирования — любой статус, кроме «Подготовки»."""
    target = proj(status, as_source=True)
    expect = "PROJECT_STATUS_CONFLICT" if status == "preparation" else "OK"
    assert code_of("branch.copy_from", MODERATOR, target) == expect


@pytest.mark.spec("FR-PORT-01")
@pytest.mark.parametrize("status", STATUSES)
def test_presale_head_reads_any_status(status: str) -> None:
    for code in ("project.read", "tree.read", "money.read", "notes.read"):
        assert code_of(code, HEAD, proj(status)) == "OK"


@pytest.mark.spec("FR-ADM-06")
@pytest.mark.parametrize("status", STATUSES)
def test_support_session_reads_any_status_without_money(status: str) -> None:
    access = decide_any(CAT, ADMIN_SUPPORT, ("tree.read",), proj(status))
    assert access.context == "support_session"
    assert (access.money, access.notes) == (False, False)


# --- Ветви движка ---------------------------------------------------------------------------


def test_pseudo_permission_is_programming_error() -> None:
    with pytest.raises(ValueError, match="псевдоправо"):
        decide(CAT, STRANGER, "authenticated", Target())


def test_project_target_needs_status() -> None:
    with pytest.raises(ValueError, match="статус"):
        decide(CAT, MODERATOR, "tree.read", Target(project_id=PROJECT))


@pytest.mark.spec("FR-SA-06")
def test_network_permission_from_foreign_network_is_404() -> None:
    assert code_of("system.health.read", subj("superadmin", network_allowed=False),
                   Target()) == "NOT_FOUND"  # fmt: skip
    assert code_of("system.health.read", SUPER, Target()) == "OK"


@pytest.mark.spec("SEC-AUTH-05")
def test_step_up_required() -> None:
    assert code_of("system.settings.write", SUPER, Target()) == "STEP_UP_REQUIRED"
    assert code_of("system.settings.write", subj("superadmin", step_up_active=True),
                   Target()) == "OK"  # fmt: skip


@pytest.mark.spec("BR-ROLE-02")
def test_unless_role_and_superadmin_has_no_user_role() -> None:
    assert code_of("dict.read", STRANGER, Target()) == "OK"
    assert code_of("dict.read", AUDITOR, Target()) == "FORBIDDEN"
    assert code_of("dict.read", SUPER, Target()) == "FORBIDDEN"


@pytest.mark.spec("BR-ROLE-08")
def test_requires_system_role() -> None:
    plain = subj(members=("project_moderator",))
    assert code_of("project.copy", plain, proj()) == "FORBIDDEN"
    assert code_of("project.copy", MODERATOR, proj()) == "OK"


@pytest.mark.spec("FR-2FA-04")
def test_preparation_hides_project_from_team() -> None:
    assert code_of("project.read", EXPERT, proj("preparation")) == "NOT_FOUND"
    assert code_of("project.read", MODERATOR, proj("preparation")) == "OK"
    both = subj("admin", members=("expert",), support=True)
    assert code_of("project.read", both, proj("preparation")) == "OK"


def test_global_permission_ignores_project_grants() -> None:
    assert code_of("tree.read", MODERATOR, Target()) == "FORBIDDEN"
    assert code_of("project.create", MODERATOR, Target()) == "OK"
    assert code_of("tree.read", ADMIN, Target()) == "FORBIDDEN"  # выдача support_session


@pytest.mark.parametrize(
    ("code", "target", "expect"),
    [
        ("trash.read", proj(kind="document"), "OK"),
        ("trash.read", proj(kind="node"), "FORBIDDEN"),
        ("tree.write", proj(disciplines=frozenset()), "FORBIDDEN"),
        ("cq.edit", proj(author_id=ME, attrs={"cq_status": "new"}), "OK"),
        ("cq.edit", proj(author_id=ME, attrs={"cq_status": "sent"}), "FORBIDDEN"),
        ("cq.edit", proj(author_id=OTHER, attrs={"cq_status": "new"}), "FORBIDDEN"),
    ],
)
def test_object_scopes_and_conditions(code: str, target: Target, expect: str) -> None:
    who = PRESALE if code == "trash.read" else EXPERT
    assert code_of(code, who, target) == expect


@pytest.mark.parametrize(
    ("who", "code", "restricted"),
    [
        (EXPERT, "tree.write", {"own_discipline"}),
        (EXPERT, "thread.resolve", {"author_or_addressee"}),
        (EXPERT, "cq.edit", {"author", "condition:cq_status_new"}),
        (PRESALE, "trash.read", {"documents_only"}),
        (ADMIN, "audit.read.admin_categories", {"admin_audit_categories"}),
        (MODERATOR, "tree.write", set()),
        (subj("moderator", members=("project_moderator", "expert")), "tree.write", set()),
    ],
)
def test_without_object_access_is_restricted(who: Subject, code: str, restricted: set[str]) -> None:
    target = Target() if code.startswith("audit") else proj()
    assert decide(CAT, who, code, target).restricted == restricted


@pytest.mark.spec("BR-ROLE-04")
def test_moderator_and_expert_get_moderator_rights() -> None:
    both = subj(members=("project_moderator", "expert"))
    access = decide(CAT, both, "tree.write", LEAF_FRONTEND)
    assert access.sources == {"project_moderator"}
    assert access.context == "member"


def test_unknown_condition_denies() -> None:
    from estimator.security.authz.engine import _condition_ok

    assert _condition_ok("nonexistent", Target()) is False


def test_limits_are_passed_to_endpoint() -> None:
    access = decide(CAT, ADMIN, "users.roles.grant", Target())
    assert access.limits == ({"roles": ["moderator", "presale", "presale_head"],
                              "not_self": True},)  # fmt: skip


@pytest.mark.spec("R-02")
def test_presale_head_context_and_member_preference() -> None:
    assert decide(CAT, HEAD, "tree.read", proj()).via_presale_head
    member_head = subj("presale_head", members=("project_moderator",))
    access = decide(CAT, member_head, "tree.read", proj())
    assert not access.via_presale_head
    assert decide(CAT, HEAD, "portfolio.read", Target()).context == "global"


@pytest.mark.spec("FR-2FA-05")
def test_decide_any_money_flags_follow_totp() -> None:
    access = decide_any(CAT, MODERATOR, ("project.read",), proj())
    assert (access.money, access.notes) == (True, True)
    no_totp = subj(members=("project_moderator",), mfa_passed=False)
    access = decide_any(CAT, no_totp, ("project.read",), proj())
    assert (access.money, access.notes) == (False, False)
    assert decide_any(CAT, EXPERT, ("project.read",), proj()).money is False


def test_decide_any_reports_closest_failure() -> None:
    with pytest.raises(AccessDenied) as exc:
        decide_any(CAT, ADMIN, ("audit.read.all", "system.settings.write"), Target())
    assert exc.value.code == "FORBIDDEN"
    with pytest.raises(AccessDenied) as exc:
        decide_any(CAT, HEAD, ("team.write", "project.join_as_moderator"), proj("archived"))
    assert exc.value.code == "PROJECT_STATUS_CONFLICT"
    assert exc.value.status == 409
    assert exc.value.detail() == {"code": "PROJECT_STATUS_CONFLICT",
                                  "project_status": "archived"}  # fmt: skip
    with pytest.raises(ValueError, match="пустой"):
        decide_any(CAT, ADMIN, (), Target())


def test_access_denied_body() -> None:
    denied = AccessDenied("FORBIDDEN", "tree.write")
    assert denied.status == 403
    assert denied.detail() == {"code": "FORBIDDEN", "permission": "tree.write"}
    assert AccessDenied("NOT_FOUND", "tree.read").detail() == {"code": "NOT_FOUND"}
    assert AccessDenied("NOT_FOUND", "tree.read").status == 404


def test_membership_subjects() -> None:
    assert [m.subject for m in MEMBERS.values()] == list(MEMBERS)
    assert subj(members=("expert", "reviewer")).disciplines == {BACKEND}


def test_access_defaults() -> None:
    access = Access(permission="x", sources=frozenset(), context="global")
    assert not access.via_presale_head
    assert (access.money, access.notes) == (False, False)
