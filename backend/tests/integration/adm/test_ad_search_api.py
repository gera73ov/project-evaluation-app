"""AUTH-017: поиск в каталоге AD и заведение заранее (FR-AUTH-AD-10, Q-16, SEC-AUTHZ-05, FR-SA-05)
— на имитации AD."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers import ldap
from estimator.db.enums import SystemRole, UserSource, UserStatus
from estimator.db.models.users import User
from tests.integration.adm.helpers import step_up
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project, discipline
from tests.support import fake_ad as support
from tests.support.fake_ad import FakeDirectory

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-AD-10")]


@pytest.fixture
async def directory(world: World, db_session: AsyncSession) -> Iterator[FakeDirectory]:
    fake = FakeDirectory()
    ldap.set_directory_factory(lambda _config: fake)
    await support.configure(db_session)
    yield fake  # type: ignore[misc]
    ldap.set_directory_factory(None)


async def _created(db: AsyncSession, object_id: Any) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = 'users.created' "
        "AND object_id = :o"), {"o": str(object_id)})  # fmt: skip
    return [r[0] for r in rows]


async def test_admin_search_and_create(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    inside = directory.add("anna.k", full_name="Ковалёва Анна", department="Продажи")
    outside = directory.add("anna.p", full_name="Петрова Анна", groups=())
    found = await admin.get("/admin/ad/search", params={"q": "Анна"})
    assert found.status_code == 200, found.text
    items = {i["login"]: i for i in found.json()["items"]}
    assert items["anna.k"]["in_access_group"] is True
    assert items["anna.k"]["department"] == "Продажи"
    assert items["anna.p"]["in_access_group"] is False
    assert items["anna.k"]["user_id"] is None

    body = {"login": "anna.k", "full_name": "Ковалёва Анна", "roles": ["presale"]}
    refused = await admin.post("/admin/users", json={**body, "login": "anna.p",
                               "ad_object_guid": str(outside.entry.object_guid)})  # fmt: skip
    assert (refused.status_code, refused.json()["code"]) == (409, "AD_USER_NOT_IN_GROUP")
    assert await db_session.scalar(select(User).where(User.login == "anna.p")) is None
    missing = await admin.post("/admin/users", json=body)
    assert missing.status_code == 422, "в режиме AD — только из каталога"

    made = await admin.post("/admin/users", json={**body,
                            "ad_object_guid": str(inside.entry.object_guid)})  # fmt: skip
    assert made.status_code == 201, made.text
    assert made.json()["activation"] is None
    user = await db_session.scalar(select(User).where(User.login == "anna.k"))
    assert user is not None
    assert (user.source, user.status) == (UserSource.AD, UserStatus.ACTIVE)
    assert made.json()["user"]["system_roles"] == [{"role": "presale", "source": "manual"}]
    assert await _created(db_session, user.id) == [{"source": "admin_ad_search",
                                                    "roles": ["presale"]}]  # fmt: skip
    again = await admin.post("/admin/users", json={**body,
                             "ad_object_guid": str(inside.entry.object_guid)})  # fmt: skip
    assert (again.status_code, again.json()["code"]) == (409, "ALREADY_EXISTS")
    known = await admin.get("/admin/ad/search", params={"q": "anna.k"})
    assert known.json()["items"][0]["user_id"] == str(user.id)

    directory.available = False
    down = await admin.get("/admin/ad/search", params={"q": "Анна"})
    assert (down.status_code, down.json()["code"]) == (503, "AUTH_SERVICE_UNAVAILABLE")


@pytest.mark.spec("SEC-AUTHZ-05")
@pytest.mark.spec("Q-16")
async def test_project_moderator_adds_from_ad(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    added = await moderator.post(f"/projects/{pid}/disciplines",
                                 json={"discipline_id": str(backend)})  # fmt: skip
    assert added.status_code == 201, added.text
    expert = await world.actor()
    team = {"members": [{"user_id": str(moderator.id), "role": "moderator"},
                        {"user_id": str(expert.id), "role": "expert",
                         "discipline_id": str(backend)}]}  # fmt: skip
    assert (await moderator.put(f"/projects/{pid}/members", json=team)).status_code == 200
    launched = await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    assert launched.status_code == 200, launched.text
    person = directory.add("oleg.s", full_name="Сидоров Олег")

    path = f"/projects/{pid}/ad-search"
    assert (await moderator.get(path, params={"q": "Олег"})).status_code == 200
    assert (await expert.get(path, params={"q": "Олег"})).status_code == 403

    made = await moderator.post(path, json={"object_guid": str(person.entry.object_guid),
                                            "discipline_id": str(backend)})  # fmt: skip
    assert made.status_code == 201, made.text
    user = await db_session.scalar(select(User).where(User.login == "oleg.s"))
    assert user is not None
    rows = [m for m in made.json()["items"] if m["user"]["id"] == str(user.id)]
    assert [m["role"] for m in rows] == ["expert"]
    [details] = await _created(db_session, user.id)
    assert details == {"source": "moderator_ad_search", "roles": [], "project_id": str(pid)}
    again = await moderator.post(path, json={"object_guid": str(person.entry.object_guid),
                                             "discipline_id": str(backend)})  # fmt: skip
    assert again.status_code == 201, "существующая учётка просто назначается"
    assert len(await _created(db_session, user.id)) == 1


@pytest.mark.spec("FR-SA-05")
async def test_superadmin_creates_admin_from_ad(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    person = directory.add("ib.lead", full_name="Руководитель ИБ")
    found = await root.get("/system/auth/ad/search", params={"q": "ib.lead"})
    assert found.status_code == 200, found.text
    guid = found.json()["items"][0]["object_guid"]
    made = await root.post("/system/admins", json={
        "login": "ignored", "email": "ignored@corp.local", "full_name": "x",
        "role": "security_auditor", "ad_object_guid": guid,
    })  # fmt: skip
    assert made.status_code == 201, made.text
    assert made.json()["activation_url"] is None
    user = await db_session.scalar(select(User).where(User.ad_object_guid == uuid.UUID(guid)))
    assert user is not None
    assert (user.login, user.full_name) == ("ib.lead", person.entry.full_name), "данные — из AD"
    local = await root.post("/system/admins", json={
        "login": "sa.new", "email": "sa.new@corp.local", "full_name": "СА",
        "role": "superadmin", "ad_object_guid": guid,
    })  # fmt: skip
    assert local.status_code == 422, "суперадминистратор — всегда локальный"
