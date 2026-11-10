"""Имитация AD для тестов (вход, поиск, синхронизация) до появления стенда Samba AD.

:class:`FakeDirectory` реализует ``auth.providers.ldap.Directory``: записи пользователей,
пароли, группы с вложенностью, флаг «AD недоступен» и журнал вызовов. Пароли тестовых
пользователей генерируются на лету (gitleaks, AGENTS 6.3.3).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers import ldap
from estimator.auth.providers.ldap import AdUnavailableError, Entry
from estimator.security.crypto import get_cipher

BASE = "DC=corp,DC=local"
ACCESS = f"CN=Estimator Users,OU=Groups,{BASE}"
MODERATORS = f"CN=Estimator Moderators,OU=Groups,{BASE}"
PRESALES = f"CN=Presale,OU=Groups,{BASE}"


def new_password() -> str:
    return "Ad-" + secrets.token_urlsafe(12)


@dataclass
class Person:
    entry: Entry
    password: str = field(repr=False)
    groups: set[str] = field(default_factory=set)


@dataclass
class FakeDirectory:
    people: dict[str, Person] = field(default_factory=dict)  # dn → человек
    #: группа → группы, в которые она вложена
    nested: dict[str, set[str]] = field(default_factory=dict)
    available: bool = True
    calls: list[str] = field(default_factory=list)

    def add(self, login: str, *, full_name: str | None = None, email: str | None = None,
            groups: Sequence[str] = (ACCESS,), disabled: bool = False,
            department: str | None = "Отдел разработки") -> Person:  # fmt: skip
        dn = f"CN={login},OU=People,{BASE}"
        entry = Entry(dn=dn, object_guid=uuid.uuid4(), login=login,
                      full_name=full_name or f"Сотрудник {login}",
                      email=email if email is not None else f"{login}@corp.local",
                      department=department, disabled=disabled)  # fmt: skip
        person = Person(entry, new_password(), set(groups))
        self.people[dn] = person
        return person

    def update(self, person: Person, **changes: Any) -> None:
        old = person.entry.dn
        person.entry = replace(person.entry, **changes)
        if person.entry.dn != old:
            self.people[person.entry.dn] = self.people.pop(old)

    def remove(self, person: Person) -> None:
        self.people.pop(person.entry.dn, None)

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if not self.available:
            raise AdUnavailableError("имитация: AD недоступен")

    def _closure(self, groups: set[str]) -> set[str]:
        out = set(groups)
        stack = list(groups)
        while stack:
            for parent in self.nested.get(stack.pop(), set()):
                if parent not in out:
                    out.add(parent)
                    stack.append(parent)
        return {g.lower() for g in out}

    def _people(self) -> Iterator[Person]:
        return iter(list(self.people.values()))

    async def ping(self) -> None:
        self._check("ping")

    async def find_user(self, login: str) -> list[Entry]:
        self._check("find_user")
        return [p.entry for p in self._people() if p.entry.login.lower() == login.lower()]

    async def check_password(self, dn: str, password: str) -> bool:
        self._check("check_password")
        person = self.people.get(dn)
        return person is not None and secrets.compare_digest(person.password, password)

    async def groups_of(self, dn: str, groups: Sequence[str]) -> set[str]:
        self._check("groups_of")
        person = self.people.get(dn)
        if person is None:
            return set()
        member = self._closure(person.groups)
        return {g for g in groups if g.lower() in member}

    async def by_guid(self, guid: uuid.UUID) -> Entry | None:
        self._check("by_guid")
        return next((p.entry for p in self._people() if p.entry.object_guid == guid), None)

    async def search(self, text: str, limit: int) -> list[Entry]:
        self._check("search")
        needle = text.lower()
        found = [p.entry for p in self._people()
                 if needle in p.entry.login.lower() or needle in p.entry.full_name.lower()
                 or needle in (p.entry.email or "").lower()]  # fmt: skip
        return sorted(found, key=lambda e: e.full_name)[:limit]


def connection(**changes: Any) -> dict[str, Any]:
    return {
        "controllers": [{"host": "dc1.corp.local", "port": 636}],
        "protocol": "ldaps", "ca_cert_pem": None, "base_dn": BASE,
        "user_filter": "(&(objectClass=user)(sAMAccountName={login}))",
        "login_attribute": "sAMAccountName", "attr_full_name": "displayName",
        "attr_email": "mail", "attr_department": "department",
        "bind_dn": f"CN=svc-estimator,OU=Service,{BASE}", "timeout_seconds": 5,
    } | changes  # fmt: skip


async def configure(
    db: AsyncSession, *, mode: str = "ad", mapping: list[tuple[str, str]] | None = None,
    access: Sequence[str] = (ACCESS,), bind_password: str | None = None,
) -> str:  # fmt: skip
    """Записать настройки AD (как после проверок) и включить режим ``mode``; вернуть пароль."""
    from tests.integration.auth.conftest import set_setting

    password = bind_password or new_password()
    await set_setting(db, "auth.mode", mode)
    await set_setting(db, ldap.CONNECTION, connection())
    await set_setting(db, ldap.BIND_PASSWORD,
                      get_cipher().encrypt_setting(ldap.BIND_PASSWORD, password))  # fmt: skip
    await set_setting(db, ldap.ACCESS_GROUPS, list(access))
    await set_setting(db, ldap.ROLE_MAPPING, {
        "enabled": mapping is not None,
        "mappings": [{"group_dn": g, "role": r} for g, r in mapping or []],
    })  # fmt: skip
    return password
