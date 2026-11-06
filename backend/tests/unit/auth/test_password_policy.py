"""AUTH-008: политика паролей FR-AUTH-LOC-02 и политика 2FA FR-2FA-02."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from estimator.auth.mfa_policy import MfaPolicy
from estimator.auth.passwords.policy import PasswordPolicy, common_passwords
from estimator.auth.providers.local import hash_password
from estimator.db.enums import SystemRole

pytestmark = pytest.mark.spec("FR-AUTH-LOC-02")

GOOD = "Grey violet ocean 2026"  # nosec B105 — тестовый пароль


def test_common_list_has_100k() -> None:
    words = common_passwords()
    assert len(words) > 95_000
    assert {"123456", "password", "qwerty"} <= words


@pytest.mark.parametrize(
    ("password", "violations"),
    [
        (GOOD, []),
        ("zq8#wv", ["too_short"]),
        ("x" * 129, ["too_long"]),
        ("Password1234", ["common"]),
        ("i.ivanov is my password", ["matches_personal"]),
        ("ivanov forever and ever", ["matches_personal"]),
        ("ivan@example.org long", ["matches_personal"]),
    ],
)
def test_violations(password: str, violations: list[str]) -> None:
    policy = PasswordPolicy()
    found = policy.violations(
        password, login="i.ivanov", full_name="Иванов Иван", email="ivan@example.org"
    )
    assert found == violations


def test_cyrillic_name_part() -> None:
    found = PasswordPolicy().violations(
        "ИВАНОВ лучший сотрудник", login="i.ivanov", full_name="Иванов Иван"
    )
    assert found == ["matches_personal"]


def test_composition_optional() -> None:
    strict = PasswordPolicy.from_setting(
        {"require_uppercase": True, "require_digit": True, "require_special": True}
    )
    assert strict.violations("long lowercase words") == ["composition"]
    assert strict.violations("Long Words 42 here!") == []
    assert PasswordPolicy().violations("long lowercase words") == []


def test_history_and_expiry() -> None:
    old = hash_password(GOOD)
    assert PasswordPolicy().violations(GOOD, previous_hashes=[old]) == ["reused"]
    assert PasswordPolicy().violations(GOOD + "!", previous_hashes=[old]) == []
    never = PasswordPolicy()
    assert not never.is_expired(datetime(2000, 1, 1, tzinfo=UTC))
    monthly = PasswordPolicy.from_setting({"expiry_days": 30})
    assert monthly.is_expired(datetime.now(UTC) - timedelta(days=31))
    assert not monthly.is_expired(datetime.now(UTC) - timedelta(days=29))


@pytest.mark.spec("FR-2FA-02")
def test_mfa_policy_by_roles() -> None:
    policy = MfaPolicy.from_setting(None)
    assert policy.required_for([SystemRole.SUPERADMIN])
    assert policy.required_for([SystemRole.MODERATOR])
    assert not policy.required_for([])
    relaxed = MfaPolicy.from_setting({"moderator": "optional", "presale": "required"})
    assert not relaxed.required_for(["moderator"])
    assert relaxed.required_for(["moderator", "presale"]), "обязателен хотя бы для одной роли"
    all_optional = MfaPolicy.from_setting(dict.fromkeys(("admin", "moderator", "presale",
        "presale_head", "security_auditor", "user"), "optional"))  # fmt: skip
    assert all_optional.required_for(["superadmin"]), "суперадминистратору — всегда"
