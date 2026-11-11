"""AUTH-013: каталог ``ldap3`` — экранирование, bind, objectGUID, ACCOUNTDISABLE (на ``MOCK_SYNC``),
проверка сертификата контроллера (на настоящем TLS-сокете с сертификатом чужого CA)."""

from __future__ import annotations

import socket
import ssl
import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server

from estimator.auth.providers.ldap import (
    AdConfig,
    AdConfigError,
    AdUnavailableError,
    Ldap3Directory,
    password_ok_but_disabled,
)

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "deploy" / "certs"))

import gen_dev_certs  # noqa: E402

pytestmark = [pytest.mark.spec("FR-AUTH-AD-02"), pytest.mark.spec("FR-AUTH-AD-13")]

BASE = "DC=corp,DC=local"
SERVICE = f"CN=svc,{BASE}"
IVAN = f"CN=ivan,{BASE}"
GUID = uuid.uuid4()


def _config(**conn: Any) -> AdConfig:
    values = {"auth.ad.connection": {
        "controllers": [{"host": "dc1", "port": 636}], "protocol": "ldaps", "base_dn": BASE,
        "bind_dn": SERVICE, "timeout_seconds": 2, **conn,
    }}  # fmt: skip
    return AdConfig.from_values(values, "svc-pass")


class MockDirectory(Ldap3Directory):
    """``ldap3`` без сети: те же поиски и bind, каталог — в памяти."""

    server = Server("dc1", get_info=OFFLINE_AD_2012_R2)

    def _connect(self, user: str | None, password: str | None) -> Any:
        conn = Connection(self.server, user=user, password=password, client_strategy=MOCK_SYNC)
        add = conn.strategy.add_entry
        add(BASE, {"objectClass": "domain"})
        add(SERVICE, {"userPassword": "svc-pass", "sAMAccountName": "svc", "objectClass": "user"})
        add(IVAN, {"userPassword": "ivan-pass", "sAMAccountName": "ivan",
                   "objectClass": ["user", "person"], "objectCategory": "person",
                   "objectGUID": GUID.bytes_le, "displayName": "Иванов Иван",
                   "mail": "ivan@corp.local", "userAccountControl": "514",
                   "department": "Разработка"})  # fmt: skip
        conn.bind()
        return conn


def test_search_bind_guid() -> None:
    directory = MockDirectory(_config())
    [entry] = directory._find_user("ivan")
    assert (entry.dn, entry.object_guid, entry.full_name) == (IVAN, GUID, "Иванов Иван")
    assert entry.disabled, "userAccountControl 514 = ACCOUNTDISABLE"
    assert directory._find_user("iv*") == [], "звёздочка экранирована"
    assert directory._find_user("*)(sAMAccountName=*") == []
    assert directory._check_password(IVAN, "ivan-pass")
    assert not directory._check_password(IVAN, "wrong")
    assert directory._by_guid(GUID) == entry
    assert directory._by_guid(uuid.uuid4()) is None
    assert [e.login for e in directory._search_people("Иван", 10)] == ["ivan"]
    directory._ping()


@pytest.mark.gherkin("G-04")
def test_disabled_account_bind_subcode() -> None:
    """AD отклоняет bind отключённой учётки (49, «data 533»), даже если пароль верный (QA-012)."""
    ad = "80090308: LdapErr: DSID-0C0903A9, comment: AcceptSecurityContext error, data {}, v1db1"
    assert password_ok_but_disabled({"result": 49, "message": ad.format("533")})
    assert not password_ok_but_disabled({"result": 49, "message": ad.format("52e")}), "неверный"
    assert not password_ok_but_disabled({"result": 49, "message": ad.format("775")}), "блокировка"
    assert not password_ok_but_disabled({"result": 0})
    assert not password_ok_but_disabled(None)


def test_service_bind_failure_is_unavailable() -> None:
    config = AdConfig.from_values({"auth.ad.connection": {
        "controllers": [{"host": "dc1", "port": 636}], "protocol": "ldaps", "base_dn": BASE,
        "bind_dn": SERVICE,
    }}, "wrong-pass")  # fmt: skip
    with pytest.raises(AdUnavailableError):
        MockDirectory(config)._find_user("ivan")


def test_config_requires_tls_and_service_account() -> None:
    with pytest.raises(AdConfigError):
        _config(protocol="ldap")
    with pytest.raises(AdConfigError):
        AdConfig.from_values({"auth.ad.connection": {"controllers": []}}, "x")
    with pytest.raises(AdConfigError):
        AdConfig.from_values(
            {"auth.ad.connection": {"controllers": [{"host": "a", "port": 1}], "base_dn": BASE,
                                    "bind_dn": SERVICE, "protocol": "ldaps"}}, None)  # fmt: skip
    tls = Ldap3Directory(_config())._tls()
    assert tls.validate == ssl.CERT_REQUIRED, "проверка сертификата не отключается"


@pytest.fixture
def tls_port(tmp_path: Path) -> Iterator[int]:
    """TLS-сокет с сертификатом, выпущенным не CA компании (как самоподписанный контроллер)."""
    gen_dev_certs.issue(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(tmp_path / "syslog.crt"), str(tmp_path / "syslog.key"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    stop = threading.Event()

    def serve() -> None:
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                client, _ = sock.accept()
            except OSError:
                continue
            try:
                with ctx.wrap_socket(client, server_side=True):
                    pass
            except (ssl.SSLError, OSError):
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield int(sock.getsockname()[1])
    stop.set()
    thread.join(2)
    sock.close()


def test_untrusted_certificate_rejected(tls_port: int) -> None:
    config = _config(controllers=[{"host": "127.0.0.1", "port": tls_port}], ca_cert_pem=None)
    with pytest.raises(AdUnavailableError):
        Ldap3Directory(config)._ping()
