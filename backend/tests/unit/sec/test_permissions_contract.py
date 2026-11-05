"""SEC-001: contracts/permissions.yaml полон и согласован с матрицами 3.3 и 3.4 SPEC."""

from __future__ import annotations

import pytest

from tests.unit._contracts import load_yaml, spec_table

pytestmark = [pytest.mark.spec("SEC-AUTHZ-02"), pytest.mark.spec("3.3"), pytest.mark.spec("3.4")]

P = load_yaml("permissions.yaml")
CATALOG: dict = P["permissions"]
PSEUDO = {"public", "token.login_step", "token.activation", "session.pre_mfa", "authenticated"}
STATUSES = ["preparation", "estimation", "consolidation", "completed", "archived"]
MONEY_PERMS = {
    "money.read",
    "money.write",
    "notes.read",
    "notes.write",
    "export.money",
    "portfolio.read",
    "portfolio.export",
}

# Какие ключи grants дают права субъекту столбца матрицы 3.3
SUBJECT_GRANTS = {
    "superadmin": ["any_authenticated", "superadmin"],
    "admin": ["any_authenticated", "user", "admin"],
    "security_auditor": ["any_authenticated", "user", "security_auditor"],
    "presale_head": ["any_authenticated", "user", "presale_head"],
    "project_moderator": ["any_authenticated", "user", "moderator", "project_moderator"],
    "expert": ["any_authenticated", "user", "expert"],
    "reviewer": ["any_authenticated", "user", "reviewer"],
    "project_presale": ["any_authenticated", "user", "project_presale"],
}


def _grants(key: str) -> list[dict]:
    out: list[dict] = []
    for g in P["grants"][key]:
        out += _grants(g["inherit"]) if "inherit" in g else [g]
    return out


def _granted(subject: str) -> set[str]:
    perms: set[str] = set()
    for key in SUBJECT_GRANTS[subject]:
        for g in _grants(key):
            if subject in g.get("unless_role", []):
                continue
            perms.add(g["permission"])
    return perms


def test_matrix_3_3_matches_spec_verbatim():
    rows = spec_table("### 3.3. Матрица прав")
    recs = P["matrix_3_3"]
    assert len(recs) == len(rows) == 45
    for i, (rec, row) in enumerate(zip(recs, rows, strict=True), 1):
        assert rec["id"] == f"M3.3-{i:02d}"
        assert rec["action"] == row[0]
        assert list(rec["cells"]) == P["matrix_subjects"]
        for subj, text in zip(P["matrix_subjects"], row[1:], strict=True):
            assert rec["cells"][subj]["spec"] == text, (rec["id"], subj)


def test_matrix_3_4_matches_spec_verbatim():
    rows = spec_table("### 3.4. Права в зависимости от статуса проекта")
    recs = P["matrix_3_4"]
    assert len(recs) == len(rows) == 16
    for i, (rec, row) in enumerate(zip(recs, rows, strict=True), 1):
        assert rec["id"] == f"M3.4-{i:02d}"
        assert rec["action"] == row[0]
        assert list(rec["statuses"]) == STATUSES
        for st, text in zip(STATUSES, row[1:], strict=True):
            assert rec["statuses"][st]["spec"] == text, (rec["id"], st)


def test_cell_effect_agrees_with_symbol():
    lead = {"✅": "allow", "❌": "deny", "👁": "view", "—": "na"}
    for rec in P["matrix_3_3"]:
        for cell in rec["cells"].values():
            sym = cell["spec"][0]
            if sym in lead:
                assert cell["effect"] == lead[sym], (rec["id"], cell)
            else:  # «свои», «автор…», «участник…»
                assert cell["effect"] in {"allow", "view"}, (rec["id"], cell)


def test_all_referenced_permissions_exist():
    refs: set[str] = set()
    for rec in P["matrix_3_3"]:
        refs |= set(rec["permissions"])
    for rec in P["matrix_3_4"]:
        refs |= set(rec.get("permissions", []))
    for gate in P["derived_status_gates"]:
        refs |= set(gate["permissions"])
    for key in P["grants"]:
        refs |= {g["permission"] for g in _grants(key)}
    assert refs - set(CATALOG) == set()


def test_every_real_permission_is_granted():
    granted = {g["permission"] for key in P["grants"] for g in _grants(key)}
    assert set(CATALOG) - PSEUDO - granted == set()


@pytest.mark.parametrize("subject", list(SUBJECT_GRANTS))
def test_grants_realise_matrix_3_3(subject: str):
    """Разрешающая ячейка имеет выдачу, запрещающая — не имеет (кроме исключения)."""
    have = _granted(subject)
    for rec in P["matrix_3_3"]:
        cell = rec["cells"][subject]
        if cell["effect"] in {"allow", "view"}:
            assert set(cell["permissions"]) <= have, (rec["id"], subject)
        elif cell["effect"] == "deny":
            allowed = set(cell.get("exception", {}).get("permissions", []))
            assert (set(rec["permissions"]) & have) <= allowed, (rec["id"], subject)


def test_money_only_from_money_roles():
    """BR-ROLE-01: права на деньги и заметки дают только модератор, пресейл, рук. пресейла."""
    for key in P["grants"]:
        perms = {g["permission"] for g in _grants(key)}
        if key not in {"project_moderator", "project_presale", "presale_head"}:
            assert perms & MONEY_PERMS == set(), key


def test_totp_gate_on_money_and_notes():
    for code in MONEY_PERMS:
        assert CATALOG[code].get("totp_gate") is True, code


def test_support_session_is_read_only_without_money():
    for g in _grants("admin"):
        if g["context"] == "support_session":
            perm = CATALOG[g["permission"]]
            assert perm.get("read_only") is True, g
            assert not perm.get("totp_gate"), g


def test_step_up_list_sec_auth_05():
    step_up = {c for c, p in CATALOG.items() if p.get("step_up")}
    assert {
        "system.auth.manage",
        "system.settings.write",
        "system.admins.manage",
        "system.users.reset_credentials",
        "users.reset_credentials",
        "system.users.anonymize",
        "audit.export",
    } <= step_up


def test_derived_gates_cover_all_statuses():
    for gate in P["derived_status_gates"]:
        assert set(gate.get("statuses") or gate.get("transitions")) == set(STATUSES)


def test_authz_examples_reference_known_ids():
    ids = {r["id"] for r in P["matrix_3_3"]} | {r["id"] for r in P["matrix_3_4"]}
    ids |= {r["id"] for r in P["rules"]} | set(CATALOG)
    assert len(P["authz_examples"]) == len(spec_table("**SEC-AUTHZ-05.**"))
    for ex in P["authz_examples"]:
        for ref in ex["by"]:
            assert ref.split(" ")[0] in ids, ref
