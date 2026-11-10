"""SEC-017: правила системных ролей без БД (BR-ROLE-02, SEC-AUTHZ-06, FR-AUTH-AD-07)."""

from __future__ import annotations

import uuid

import pytest
import yaml

from estimator.api.common.errors import ApiError
from estimator.db.enums import SystemRole as R
from estimator.security.authz import role_rules
from tests.contract.openapi_impl import ROOT

pytestmark = [pytest.mark.spec("BR-ROLE-02")]

ADMIN, SUPER, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _code(exc: pytest.ExceptionInfo[ApiError]) -> tuple[str, dict[str, object]]:
    return exc.value.code, exc.value.extensions


def test_incompatible_matches_contract() -> None:
    doc = yaml.safe_load((ROOT / "contracts" / "permissions.yaml").read_text(encoding="utf-8"))
    rule = next(r for r in doc["rules"] if r["id"] == "R-COMPAT")
    for role, banned in rule["incompatible"].items():
        system = {b for b in banned if b != "project_member"}
        assert {r.value for r in role_rules.INCOMPATIBLE[R(role)]} == system
        assert ("project_member" in banned) == (R(role) in role_rules.NO_PROJECTS)


@pytest.mark.parametrize(
    ("roles", "clash"),
    [
        ({R.ADMIN, R.MODERATOR, R.PRESALE, R.PRESALE_HEAD}, []),
        ({R.SUPERADMIN}, []),
        ({R.SECURITY_AUDITOR}, []),
        ({R.SUPERADMIN, R.ADMIN}, ["admin", "superadmin"]),
        ({R.SECURITY_AUDITOR, R.PRESALE}, ["presale", "security_auditor"]),
        ({R.SUPERADMIN, R.SECURITY_AUDITOR}, ["security_auditor", "superadmin"]),
    ],
)
def test_combinations(roles: set[R], clash: list[str]) -> None:
    assert role_rules.conflicts(roles) == clash
    if clash:
        with pytest.raises(ApiError) as exc:
            role_rules.check_combination(roles)
        assert _code(exc) == ("ROLE_INCOMPATIBLE", {"conflicting_roles": clash})
    else:
        role_rules.check_combination(roles)


def test_superadmin_and_auditor_never_join_projects() -> None:
    role_rules.check_project_member({R.MODERATOR, R.ADMIN})
    for role in (R.SUPERADMIN, R.SECURITY_AUDITOR):
        with pytest.raises(ApiError) as exc:
            role_rules.check_project_member({role})
        assert _code(exc) == ("ROLE_INCOMPATIBLE", {"conflicting_roles": [role.value]})


def _change(
    actor: uuid.UUID, actor_roles: set[R], before: set[R], after: set[R], **kw: bool
) -> None:
    role_rules.check_change(
        actor_id=actor, actor_roles=actor_roles, target_id=OTHER, before=before, after=after, **kw
    )


@pytest.mark.spec("SEC-AUTHZ-06")
def test_admin_grants_only_working_roles() -> None:
    _change(ADMIN, {R.ADMIN}, set(), {R.MODERATOR, R.PRESALE, R.PRESALE_HEAD})
    _change(ADMIN, {R.ADMIN}, {R.MODERATOR}, set())
    for role in (R.ADMIN, R.SECURITY_AUDITOR):
        with pytest.raises(ApiError) as exc:
            _change(ADMIN, {R.ADMIN}, set(), {role})
        assert _code(exc) == ("FORBIDDEN", {"permission": "system.admins.manage"})
    with pytest.raises(ApiError) as exc:  # снять «Администратор» тоже нельзя
        _change(ADMIN, {R.ADMIN}, {R.ADMIN}, set())
    assert _code(exc)[0] == "FORBIDDEN"


@pytest.mark.spec("SEC-AUTHZ-06")
def test_superadmin_grants_admin_and_auditor_only() -> None:
    _change(SUPER, {R.SUPERADMIN}, set(), {R.ADMIN})
    _change(SUPER, {R.SUPERADMIN}, set(), {R.SECURITY_AUDITOR})
    _change(SUPER, {R.SUPERADMIN}, {R.ADMIN, R.MODERATOR}, {R.MODERATOR})
    with pytest.raises(ApiError) as exc:
        _change(SUPER, {R.SUPERADMIN}, set(), {R.MODERATOR})
    assert _code(exc) == ("FORBIDDEN", {"permission": "users.roles.grant"})
    with pytest.raises(ApiError) as exc:  # аудитор ИБ с рабочей ролью несовместим
        _change(SUPER, {R.SUPERADMIN}, {R.PRESALE}, {R.PRESALE, R.SECURITY_AUDITOR})
    assert _code(exc) == (
        "ROLE_INCOMPATIBLE",
        {"conflicting_roles": ["presale", "security_auditor"]},
    )


@pytest.mark.spec("SEC-AUTHZ-06")
def test_nobody_changes_own_roles_or_superadmin_role() -> None:
    with pytest.raises(ApiError) as exc:
        role_rules.check_change(actor_id=ADMIN, actor_roles={R.ADMIN}, target_id=ADMIN,
                                before={R.ADMIN}, after={R.ADMIN, R.MODERATOR})  # fmt: skip
    assert _code(exc) == ("FORBIDDEN", {"permission": "users.roles.grant"})
    # Без изменений — не ошибка
    role_rules.check_change(actor_id=ADMIN, actor_roles={R.ADMIN}, target_id=ADMIN,
                            before={R.ADMIN}, after={R.ADMIN})  # fmt: skip
    for before, after in (({R.ADMIN}, {R.SUPERADMIN}), ({R.SUPERADMIN}, set())):
        with pytest.raises(ApiError) as exc:
            _change(SUPER, {R.SUPERADMIN}, before, after)
        assert _code(exc) == ("FORBIDDEN", {"permission": "system.admins.manage"})


@pytest.mark.spec("FR-AUTH-AD-07")
def test_ad_group_roles_are_locked_when_mapping_is_on() -> None:
    _change(ADMIN, {R.ADMIN}, set(), {R.PRESALE_HEAD}, ad_mapping_locked=True)
    with pytest.raises(ApiError) as exc:
        _change(ADMIN, {R.ADMIN}, set(), {R.MODERATOR}, ad_mapping_locked=True)
    assert _code(exc) == ("ROLE_INCOMPATIBLE", {"conflicting_roles": ["moderator"]})
