"""AUTH-015: проверки и сохранение настроек AD, отчёт и пересчёт ролей по группам (FR-AUTH-AD-03,
FR-AUTH-AD-04, FR-AUTH-AD-07, SEC-AUTH-05, SEC-AUTH-07) — на имитации AD."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers import ldap
from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from tests.integration.adm.helpers import step_up
from tests.integration.core.conftest import Actor, World
from tests.support import fake_ad as support
from tests.support.fake_ad import FakeDirectory, Person

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-AD-03")]

PATH = "/system/settings/auth"


@pytest.fixture
def directory() -> Iterator[FakeDirectory]:
    fake = FakeDirectory()
    ldap.set_directory_factory(lambda _config: fake)
    yield fake
    ldap.set_directory_factory(None)


async def _root(world: World) -> Actor:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    return root


def _form(password: str, **conn: Any) -> dict[str, Any]:
    return {ldap.CONNECTION: support.connection(**conn), ldap.BIND_PASSWORD: password,
            ldap.ACCESS_GROUPS: [support.ACCESS]}  # fmt: skip


async def _audit(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"), {"e": event}
    )
    return [r[0] for r in rows]


@pytest.mark.spec("FR-AUTH-AD-04")
async def test_save_only_after_both_checks(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    root = await _root(world)
    tester = directory.add("tester")
    secret = support.new_password()
    form = _form(secret)

    early = await root.put(PATH, json={"values": form})
    assert (early.status_code, early.json()["code"]) == (409, "AD_CHECKS_REQUIRED")
    assert early.json()["missing"] == ["connection", "login"]

    connected = await root.post("/system/auth/ad/test-connection", json={"values": form})
    assert connected.status_code == 200, connected.text
    assert connected.json()["ok"] is True
    half = await root.put(PATH, json={"values": form})
    assert half.json()["missing"] == ["login"]

    wrong = await root.post("/system/auth/ad/test-login",
                            json={"values": form, "login": "tester", "password": "nope-nope"})  # fmt: skip
    assert (wrong.json()["ok"], wrong.json()["detail"]) == (False, "Неверный пароль")
    assert wrong.json()["user"] is None
    logged = await root.post("/system/auth/ad/test-login",
                             json={"values": form, "login": "tester", "password": tester.password})  # fmt: skip
    assert logged.status_code == 200, logged.text
    body = logged.json()
    assert body["ok"] is True
    assert body["user"]["in_access_group"] is True
    assert body["user"]["groups"] == [support.ACCESS]

    other = await root.put(PATH, json={"values": _form(secret, timeout_seconds=7)})
    assert other.json()["missing"] == ["connection", "login"], "другие параметры — снова проверки"
    saved = await root.put(PATH, json={"values": form})
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"][ldap.BIND_PASSWORD] == {"set": True}
    assert secret not in saved.text
    [changed] = await _audit(db_session, "system.ad_settings.changed")
    assert ldap.BIND_PASSWORD in changed["changes"]
    assert secret not in str(changed)
    config = await ldap.load_config(db_session)
    assert config.bind_password == secret, "пароль хранится зашифрованным и читается"
    stored = await db_session.scalar(
        text("SELECT value::text FROM system_settings WHERE key = 'auth.ad.bind_password'")
    )
    assert secret not in str(stored)

    # сохранённый пароль подставляется в проверку, пока контроллеры и bind не менялись
    keep = {**form, ldap.BIND_PASSWORD: {"set": True}}
    again = await root.post("/system/auth/ad/test-connection", json={"values": keep})
    assert again.json()["ok"] is True
    moved = {**keep, ldap.CONNECTION: support.connection(bind_dn="CN=other,DC=corp,DC=local")}
    refused = await root.post("/system/auth/ad/test-connection", json={"values": moved})
    assert refused.json()["ok"] is False


async def test_checks_report_problems(world: World, directory: FakeDirectory) -> None:
    root = await _root(world)
    outsider = directory.add("outsider", groups=())
    form = _form(support.new_password())
    response = await root.post("/system/auth/ad/test-login",
                               json={"values": form, "login": "outsider",
                                     "password": outsider.password})  # fmt: skip
    body = response.json()
    assert (body["ok"], body["user"]["in_access_group"]) == (False, False)
    assert body["detail"] == "Пользователь не состоит в группе доступа"
    empty = await root.post("/system/auth/ad/test-connection", json={"values": {}})
    assert empty.json()["ok"] is False, "параметры не заданы"
    directory.available = False
    down = await root.post("/system/auth/ad/test-connection", json={"values": form})
    assert down.json()["ok"] is False
    assert down.json()["detail"].startswith("Не удалось подключиться к AD")


async def _ad_user(db: AsyncSession, person: Person, *roles: SystemRole) -> User:
    user = User(login=person.entry.login, full_name=person.entry.full_name, source=UserSource.AD,
                ad_object_guid=person.entry.object_guid, status=UserStatus.ACTIVE)  # fmt: skip
    db.add(user)
    await db.flush()
    for role in roles:
        db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    await db.flush()
    return user


async def _roles(db: AsyncSession, user: User) -> dict[str, str]:
    rows = await db.execute(
        select(UserRole.role, UserRole.source).where(UserRole.user_id == user.id)
    )
    return {SystemRole(r).value: RoleSource(s).value for r, s in rows.all()}


@pytest.mark.spec("FR-AUTH-AD-07")
async def test_role_mapping_preview_enable_disable(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    root = await _root(world)
    await support.configure(db_session, mode="local")
    mod = directory.add("mod", groups=(support.ACCESS, support.MODERATORS))
    manual = directory.add("manual")
    a = await _ad_user(db_session, mod)
    b = await _ad_user(db_session, manual, SystemRole.MODERATOR, SystemRole.ADMIN)
    mapping = {"enabled": True, "mappings": [{"group_dn": support.MODERATORS, "role": "moderator"}]}

    preview = await root.post("/system/auth/role-mapping/preview",
                              json={"values": {ldap.ROLE_MAPPING: mapping}})  # fmt: skip
    assert preview.status_code == 200, preview.text
    items = {i["login"]: (i["added"], i["removed"]) for i in preview.json()["items"]}
    assert items == {"manual": ([], ["moderator"]), "mod": (["moderator"], [])}
    assert await _roles(db_session, a) == {}, "отчёт ничего не меняет"

    saved = await root.put(PATH, json={"values": {ldap.ROLE_MAPPING: mapping}})
    assert saved.status_code == 200, saved.text
    assert await _roles(db_session, a) == {"moderator": "ad_group"}
    assert await _roles(db_session, b) == {"admin": "manual"}, "ручная роль снята, admin не трогаем"
    assert await _audit(db_session, "users.ad_role_mapping.report") == [
        {"roles_to_remove": 1, "applied": True, "actor": "system"}
    ]

    off = await root.put(PATH, json={"values": {ldap.ROLE_MAPPING: {**mapping, "enabled": False}}})
    assert off.status_code == 200, off.text
    assert await _roles(db_session, a) == {"moderator": "manual"}, "выключение — роли ручные"

    directory.available = False
    down = await root.post("/system/auth/role-mapping/preview",
                           json={"values": {ldap.ROLE_MAPPING: mapping}})  # fmt: skip
    assert (down.status_code, down.json()["code"]) == (503, "AUTH_SERVICE_UNAVAILABLE")
