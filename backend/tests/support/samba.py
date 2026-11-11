"""QA-012 · настоящий AD для тестов: Samba AD DC профиля test (SPEC 17.1, Q-50; INF-004).

Наборы ``tests/integration/ad`` и приёмочные шаги ``tests/acceptance/steps/ad_steps.py`` идут
против контроллера ``deploy/samba-ad`` (``make up-test``, затем ``make test-ad``). Без переменных
``TEST_SAMBA_*`` тесты с фикстурой :func:`samba` пропускаются — в обычном CI Samba нет.

Переменные (их задаёт ``make test-ad``):

* ``TEST_SAMBA_HOST`` — имя контроллера из сертификата, ``dc1.test.estimator.local``;
* ``TEST_SAMBA_LDAPS_PORT`` (636) и ``TEST_SAMBA_LDAP_PORT`` (389, StartTLS);
* ``TEST_SAMBA_CA_FILE`` — dev-УЦ, которым выпущен сертификат контроллера;
* ``TEST_SAMBA_ADMIN_PASSWORD`` — Administrator домена (заводит и меняет тестовые учётки);
* ``TEST_SAMBA_SERVICE_PASSWORD`` — пароль сервисной учётки ``svc-estimator`` (seed.sh).

Каждый тест заводит свои учётки и группы с префиксом ``qa-ad-`` и удаляет их после себя: Samba
общий для всех тестов прогона и для сценариев Playwright (у них префикс ``e2e-fe-``), сидовые
записи ``seed.sh`` тесты только читают. Пароли генерируются на лету (gitleaks, AGENTS 6.3.3).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import secrets
import ssl
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers import ldap
from estimator.security.crypto import get_cipher

BASE = "DC=test,DC=estimator,DC=local"
ROOT = f"OU=Estimator,{BASE}"
USERS = f"OU=Users,{ROOT}"
GROUPS = f"OU=Groups,{ROOT}"
SERVICE_DN = f"CN=svc-estimator,OU=Service,{ROOT}"
ADMIN_DN = f"CN=Administrator,CN=Users,{BASE}"
#: Группы из seed.sh: est-access ← est-experts ← est-presale-team; est-moderators ⊂ est-access.
ACCESS = f"CN=est-access,{GROUPS}"
EXPERTS = f"CN=est-experts,{GROUPS}"
MODERATORS = f"CN=est-moderators,{GROUPS}"
PRESALE_LEADS = f"CN=est-presale-leads,{GROUPS}"
PREFIX = "qa-ad-"
#: userAccountControl: обычная учётка и отключённая (NORMAL_ACCOUNT | ACCOUNTDISABLE).
NORMAL, DISABLED = 0x0200, 0x0202

ENV = ("TEST_SAMBA_HOST", "TEST_SAMBA_CA_FILE", "TEST_SAMBA_ADMIN_PASSWORD",
       "TEST_SAMBA_SERVICE_PASSWORD")  # fmt: skip


def new_password() -> str:
    """Пароль под политику сложности AD: заглавная, строчная, цифра, знак."""
    return "Qa-" + secrets.token_urlsafe(12) + "7z!"


@dataclass(frozen=True)
class Env:
    host: str
    ldaps_port: int
    ldap_port: int
    ca_pem: str
    admin_password: str = field(repr=False)
    service_password: str = field(repr=False)

    @classmethod
    def load(cls) -> Env | None:
        if not all(os.environ.get(name) for name in ENV):
            return None
        with open(os.environ["TEST_SAMBA_CA_FILE"], encoding="ascii") as fh:
            ca = fh.read()
        return cls(
            host=os.environ["TEST_SAMBA_HOST"],
            ldaps_port=int(os.environ.get("TEST_SAMBA_LDAPS_PORT") or 636),
            ldap_port=int(os.environ.get("TEST_SAMBA_LDAP_PORT") or 389),
            ca_pem=ca, admin_password=os.environ["TEST_SAMBA_ADMIN_PASSWORD"],
            service_password=os.environ["TEST_SAMBA_SERVICE_PASSWORD"],
        )  # fmt: skip


@dataclass
class AdUser:
    """Учётка, заведённая тестом в Samba."""

    login: str
    dn: str
    password: str = field(repr=False)
    full_name: str
    object_guid: uuid.UUID


class Samba:
    """Администрирование тестового домена по LDAPS от имени Administrator."""

    def __init__(self, env: Env) -> None:
        self.env = env
        self._created: list[str] = []  # DN в порядке создания; удаляются в обратном
        self._memberships: list[tuple[str, str]] = []  # (группа, член) в чужих группах
        self._conn: Any = None

    # подключение

    def _tls(self) -> Any:
        from ldap3 import Tls

        return Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT,
                   ca_certs_data=self.env.ca_pem)  # fmt: skip

    @property
    def conn(self) -> Any:
        if self._conn is None:
            from ldap3 import Connection, Server

            server = Server(self.env.host, port=self.env.ldaps_port, use_ssl=True,
                            tls=self._tls(), connect_timeout=5)  # fmt: skip
            self._conn = Connection(server, ADMIN_DN, self.env.admin_password, auto_bind=True,
                                    raise_exceptions=True, receive_timeout=10)  # fmt: skip
        return self._conn

    def close(self) -> None:
        from ldap3 import MODIFY_DELETE
        from ldap3.core.exceptions import LDAPException

        if self._conn is None:
            return
        # член уже удалён вместе со своей записью; запись тест мог удалить сам
        for group, member in reversed(self._memberships):
            with contextlib.suppress(LDAPException):
                self.conn.modify(group, {"member": [(MODIFY_DELETE, [member])]})
        for dn in reversed(self._created):
            with contextlib.suppress(LDAPException):
                self.conn.delete(dn)
        self._conn.unbind()
        self._conn = None

    # учётки и группы

    def name(self, hint: str = "") -> str:
        """Уникальный sAMAccountName (≤ 20 символов) с префиксом ``qa-ad-``."""
        hint = "".join(c for c in hint.lower() if c.isalnum())[:5]
        return f"{PREFIX}{hint}{secrets.token_hex(4)}"[:20]

    def _guid(self, dn: str) -> uuid.UUID:
        self.conn.search(dn, "(objectClass=*)", search_scope="BASE", attributes=["objectGUID"])
        raw = self.conn.response[0]["raw_attributes"]["objectGUID"][0]
        return uuid.UUID(bytes_le=bytes(raw))

    def add_user(self, hint: str = "", *, full_name: str | None = None,
                 groups: Sequence[str] = (ACCESS,), disabled: bool = False,
                 login: str | None = None, mail: str | None = None) -> AdUser:  # fmt: skip
        login = login or self.name(hint)
        dn = f"CN={login},{USERS}"
        password = new_password()
        full_name = full_name or f"Тест {login}"
        attrs = {
            "sAMAccountName": login, "displayName": full_name,
            "userPrincipalName": f"{login}@test.estimator.local",
            "mail": mail or f"{login}@test.estimator.local", "department": "QA",
            "unicodePwd": f'"{password}"'.encode("utf-16-le"),
            "userAccountControl": DISABLED if disabled else NORMAL,
        }  # fmt: skip
        self.conn.add(dn, ["top", "person", "organizationalPerson", "user"], attrs)
        self._created.append(dn)
        for group in groups:
            self.add_member(group, dn)
        return AdUser(login, dn, password, full_name, self._guid(dn))

    def add_group(self, hint: str = "", *, member_of: Sequence[str] = ()) -> str:
        name = self.name(hint or "grp")
        dn = f"CN={name},{GROUPS}"
        self.conn.add(dn, ["top", "group"], {"sAMAccountName": name})
        self._created.append(dn)
        for parent in member_of:
            self.add_member(parent, dn)
        return dn

    def add_member(self, group: str, member: str) -> None:
        from ldap3 import MODIFY_ADD

        self.conn.modify(group, {"member": [(MODIFY_ADD, [member])]})
        self._memberships.append((group, member))

    def remove_member(self, group: str, member: str) -> None:
        from ldap3 import MODIFY_DELETE

        self.conn.modify(group, {"member": [(MODIFY_DELETE, [member])]})

    def set_disabled(self, user: AdUser, disabled: bool = True) -> None:
        from ldap3 import MODIFY_REPLACE

        uac = DISABLED if disabled else NORMAL
        self.conn.modify(user.dn, {"userAccountControl": [(MODIFY_REPLACE, [uac])]})

    def rename(self, user: AdUser, new_login: str, *, full_name: str | None = None) -> None:
        """Переименование логина в AD: sAMAccountName, UPN и CN записи (objectGUID тот же)."""
        from ldap3 import MODIFY_REPLACE

        changes = {
            "sAMAccountName": [(MODIFY_REPLACE, [new_login])],
            "userPrincipalName": [(MODIFY_REPLACE, [f"{new_login}@test.estimator.local"])],
        }
        if full_name:
            changes["displayName"] = [(MODIFY_REPLACE, [full_name])]
        self.conn.modify(user.dn, changes)
        self.conn.modify_dn(user.dn, f"CN={new_login}")
        old = user.dn
        user.dn, user.login = f"CN={new_login},{USERS}", new_login
        if full_name:
            user.full_name = full_name
        self._created[self._created.index(old)] = user.dn
        self._memberships = [(g, user.dn if m == old else m) for g, m in self._memberships]

    def delete(self, user: AdUser) -> None:
        self.conn.delete(user.dn)

    # настройки приложения

    def connection(self, *, protocol: str = "ldaps", ca_pem: str | None = "",
                   controllers: list[dict[str, Any]] | None = None,
                   **changes: Any) -> dict[str, Any]:  # fmt: skip
        port = self.env.ldaps_port if protocol == "ldaps" else self.env.ldap_port
        return {
            "controllers": controllers or [{"host": self.env.host, "port": port}],
            "protocol": protocol, "ca_cert_pem": self.env.ca_pem if ca_pem == "" else ca_pem,
            "base_dn": BASE, "user_filter": ldap.DEFAULT_FILTER,
            "login_attribute": "sAMAccountName", "attr_full_name": "displayName",
            "attr_email": "mail", "attr_department": "department",
            "bind_dn": SERVICE_DN, "timeout_seconds": 3,
        } | changes  # fmt: skip

    async def configure(
        self, db: AsyncSession, *, mode: str = "ad", access: Sequence[str] = (ACCESS,),
        mapping: list[tuple[str, str]] | None = None, **connection: Any,
    ) -> None:  # fmt: skip
        """Записать настройки AD на этот контроллер (как после обеих проверок) и режим ``mode``."""
        from tests.integration.auth.conftest import set_setting

        conn = self.connection(**connection)
        password = self.env.service_password
        await set_setting(db, "auth.mode", mode)
        await set_setting(db, ldap.CONNECTION, conn)
        await set_setting(db, ldap.BIND_PASSWORD,
                          get_cipher().encrypt_setting(ldap.BIND_PASSWORD, password))  # fmt: skip
        await set_setting(db, ldap.ACCESS_GROUPS, list(access))
        await set_setting(db, ldap.ROLE_MAPPING, {
            "enabled": mapping is not None,
            "mappings": [{"group_dn": g, "role": r} for g, r in mapping or []],
        })  # fmt: skip
        now = dt.datetime.now(dt.UTC).isoformat()
        values = {ldap.CONNECTION: conn, ldap.ACCESS_GROUPS: list(access)}
        await set_setting(db, "auth.ad.verification", {
            "params_sha256": ldap.fingerprint(values, password),
            "connection_ok_at": now, "login_ok_at": now,
        })  # fmt: skip


@pytest.fixture
def samba_env() -> Env:
    env = Env.load()
    if env is None:
        pytest.skip("Samba AD не настроен (TEST_SAMBA_*): запуск — make up-test && make test-ad")
    return env


@pytest.fixture
def samba(samba_env: Env) -> Iterator[Samba]:
    """Администрирование Samba; учётки и группы теста удаляются после него. Каталог приложения —
    настоящий ``Ldap3Directory`` (имитация AD не подставляется)."""
    ldap.set_directory_factory(None)
    admin = Samba(samba_env)
    try:
        yield admin
    finally:
        admin.close()
