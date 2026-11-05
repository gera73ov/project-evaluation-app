"""AUTH-001: интерфейс провайдеров, реестр, параметры Argon2id (без БД)."""

from __future__ import annotations

import uuid

import pytest
from argon2 import PasswordHasher, Type

from estimator.auth.policy import SessionPolicy
from estimator.auth.providers import (
    LOCAL,
    AuthProvider,
    AuthResult,
    Credentials,
    Identity,
    ProviderNotAvailableError,
    get_provider,
    register_provider,
    registered_providers,
    unregister_provider,
)
from estimator.auth.providers.local import (
    MEMORY_KIB,
    PARALLELISM,
    TIME_COST,
    LocalProvider,
    hash_password,
    needs_rehash,
    verify_password,
)
from estimator.db.enums import SystemRole

pytestmark = pytest.mark.spec("FR-AUTH-AD-11")


def test_credentials_repr_hides_password() -> None:
    assert "s3cret" not in repr(Credentials("i.ivanov", "s3cret"))


def test_result_requires_contract_reason() -> None:
    assert AuthResult.failure("wrong_password").ok is False
    with pytest.raises(ValueError, match="контракта"):
        AuthResult.failure("bad_reason")
    with pytest.raises(ValueError, match="ровно одно"):
        AuthResult()
    ok = AuthResult.success(Identity("local", "1", "i.ivanov"))
    assert ok.ok
    assert ok.reason is None


@pytest.mark.spec("ARCH-06")
def test_registry_local_and_custom() -> None:
    assert LOCAL in registered_providers()
    assert isinstance(get_provider(LOCAL), LocalProvider)
    with pytest.raises(ProviderNotAvailableError):
        get_provider("kerberos")

    class Fake(AuthProvider):
        name = "fake"

        async def authenticate(self, session, credentials):  # type: ignore[no-untyped-def]
            return AuthResult.success(Identity("fake", "x", credentials.login))

    register_provider("fake", Fake)
    try:
        with pytest.raises(ValueError, match="уже"):
            register_provider("fake", Fake)
        assert isinstance(get_provider("fake"), Fake)
    finally:
        unregister_provider("fake")
    assert "fake" not in registered_providers()


@pytest.mark.spec("SEC-AUTH-01")
def test_argon2id_parameters_not_below_spec() -> None:
    assert MEMORY_KIB >= 64 * 1024
    assert TIME_COST >= 3
    assert 1 <= PARALLELISM <= 4
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert f"m={MEMORY_KIB},t={TIME_COST},p={PARALLELISM}" in hashed
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong")
    assert not verify_password("not-a-hash", "x")
    assert not needs_rehash(hashed)


@pytest.mark.spec("SEC-AUTH-01")
def test_weaker_or_foreign_hash_needs_rehash() -> None:
    weak = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
    assert needs_rehash(weak.hash("pw"))
    argon2i = PasswordHasher(time_cost=3, memory_cost=MEMORY_KIB, parallelism=2, type=Type.I)
    assert needs_rehash(argon2i.hash("pw"))
    assert needs_rehash("$2b$12$bcrypthashbcrypthashbcrypthashbcrypthashbcrypthash")


@pytest.mark.spec("BR-ROLE-01")
def test_shortest_idle_timeout_wins() -> None:
    policy = SessionPolicy.from_settings(
        {"idle_minutes_user": 60, "idle_minutes_admin": 15, "absolute_hours": 12},
        {"max_sessions": 3},
    )
    assert policy.idle_seconds([SystemRole.MODERATOR]) == 3600
    assert policy.idle_seconds(["moderator", "admin"]) == 900
    assert policy.idle_seconds([]) == 3600
    assert policy.max_sessions == 3
    assert policy.absolute_seconds == 12 * 3600
    assert SessionPolicy.from_settings(None) == SessionPolicy()
    # админский тайм-аут длиннее пользовательского — всё равно берётся кратчайший
    odd = SessionPolicy(idle_minutes_user=10, idle_minutes_admin=15)
    assert odd.idle_seconds([SystemRole.ADMIN]) == 600


def test_identity_user_id_optional() -> None:
    uid = uuid.uuid4()
    assert Identity("ad", "guid", "x", {"email": None}, uid).user_id == uid
