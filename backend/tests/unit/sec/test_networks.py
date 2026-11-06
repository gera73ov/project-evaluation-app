"""FR-SA-06: адрес клиента и список security.admin_networks."""

from __future__ import annotations

import pytest

from estimator.security.networks import address_allowed

pytestmark = pytest.mark.spec("FR-SA-06")


@pytest.mark.parametrize(
    ("ip", "networks", "allowed"),
    [
        ("203.0.113.5", [], True),
        ("10.1.2.3", ["10.0.0.0/8"], True),
        ("192.168.1.1", ["10.0.0.0/8"], False),
        ("2001:db8::1", ["2001:db8::/32", "10.0.0.0/8"], True),
        ("10.1.2.3", ["2001:db8::/32"], False),
        ("10.1.2.3", ["10.1.2.3/24"], True),  # хост в записи сети не ломает разбор
        ("unknown", ["10.0.0.0/8"], False),
    ],
)
def test_address_allowed(ip: str, networks: list[str], allowed: bool) -> None:
    assert address_allowed(ip, networks) is allowed
