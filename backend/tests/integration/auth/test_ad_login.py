"""AUTH-013, AUTH-014: вход через AD на имитации каталога (TC-AUTH-01, FR-AUTH-AD-05…07, -09,
-13; FR-SA-03)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from tests.integration.auth.conftest import complete_setup
from tests.integration.auth.helpers import PASSWORD, make_user
from tests.support import fake_ad as support
from tests.support.fake_ad import FakeDirectory, Person

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-AD-13")]


async def _login(api: httpx.AsyncClient, login: str, password: str) -> httpx.Response:
    return await api.post("/api/v1/auth/login", json={"login": login, "password": password})


async def _reasons(db: AsyncSession, login: str) -> list[str]:
    rows = await db.execute(text(
        "SELECT details->>'reason' FROM audit.audit_log WHERE event_type = 'auth.login.failed' "
        "AND login = :l ORDER BY id"), {"l": login})  # fmt: skip
    return [r[0] for r in rows]


async def _events(db: AsyncSession, event: str, object_id: Any) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = :e AND object_id = :o ORDER BY id"
    ), {"e": event, "o": str(object_id)})  # fmt: skip
    return [{k: v for k, v in r[0].items() if k != "actor"} for r in rows]


async def _user(db: AsyncSession, person: Person) -> User:
    user = await db.scalar(
        select(User).where(User.ad_object_guid == person.entry.object_guid)
        .execution_options(populate_existing=True)
    )  # fmt: skip
    assert user is not None
    return user


async def _roles(db: AsyncSession, user: User) -> dict[str, str]:
    rows = await db.execute(
        select(UserRole.role, UserRole.source).where(UserRole.user_id == user.id)
    )
    return {SystemRole(r).value: RoleSource(s).value for r, s in rows.all()}


@pytest.fixture
async def ad(db_session: AsyncSession, fake_ad: FakeDirectory) -> FakeDirectory:
    await complete_setup(db_session)
    await support.configure(db_session)
    return fake_ad


@pytest.mark.spec("FR-AUTH-AD-06")
async def test_first_login_creates_user_and_rename_keeps_it(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    person = ad.add("ivanov", full_name="Иванов Иван")
    response = await _login(api, "ivanov", person.password)
    assert response.status_code == 200, response.text
    assert response.json()["step"] == "done"
    user = await _user(db_session, person)
    assert (user.source, user.status, user.full_name) == (UserSource.AD, UserStatus.ACTIVE,
                                                          "Иванов Иван")  # fmt: skip
    assert user.password_hash is None
    assert await _roles(db_session, user) == {}, "роль «Пользователь» — без системных ролей"
    assert await _events(db_session, "users.created", user.id) == [
        {"source": "ad_jit", "roles": []}
    ]

    ad.update(person, login="ivanov.i", full_name="Иванов Иван Иванович")
    api.cookies.clear()
    again = await _login(api, "ivanov.i", person.password)
    assert again.status_code == 200, again.text
    renamed = await _user(db_session, person)
    assert renamed.id == user.id, "переименование в AD не создаёт дубль"
    assert renamed.login == "ivanov.i"
    [changed] = await _events(db_session, "users.updated", user.id)
    assert changed["changes"]["login"] == ["ivanov", "ivanov.i"]


@pytest.mark.spec("FR-AUTH-AD-05")
async def test_refusals_are_uniform_and_reasons_audited(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    ok = ad.add("petrov")
    disabled = ad.add("sidorov", disabled=True)
    outsider = ad.add("smirnov", groups=())
    twin = ad.add("twin")
    ad.add("TWIN")  # две записи с одним логином
    cases = [
        ("petrov", "wrong-" + ok.password, "wrong_password"),
        ("sidorov", disabled.password, "ad_account_disabled"),
        ("smirnov", outsider.password, "ad_not_in_group"),
        ("nobody", "whatever-password", "user_not_found"),
        ("twin", twin.password, "ad_ambiguous"),
    ]
    bodies = set()
    for login, password, reason in cases:
        response = await _login(api, login, password)
        assert response.status_code == 401, (login, response.text)
        bodies.add((response.json()["code"], response.json().get("auth_mode")))
        assert (await _reasons(db_session, login))[-1] == reason
    assert bodies == {("LOGIN_FAILED", "ad")}, "один и тот же ответ на любой отказ"
    assert ad.calls.count("check_password") >= len(cases), "bind и для ненайденного логина"
    created = await db_session.scalar(select(User).where(User.login.in_(["sidorov", "smirnov"])))
    assert created is None, "без проверок AD учётка не создаётся"


async def test_nested_group_gives_access(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    team = f"CN=Team A,OU=Groups,{support.BASE}"
    ad.nested[team] = {support.ACCESS}
    person = ad.add("kuznetsov", groups=(team,))
    response = await _login(api, "kuznetsov", person.password)
    assert response.status_code == 200, response.text


@pytest.mark.spec("FR-AUTH-AD-09")
async def test_ad_unavailable_is_503(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    person = ad.add("popov")
    ad.available = False
    response = await _login(api, "popov", person.password)
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_SERVICE_UNAVAILABLE"
    assert await _reasons(db_session, "popov") == ["ad_unavailable"]


@pytest.mark.spec("FR-SA-03")
async def test_superadmin_never_goes_to_ad(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    from tests.integration.auth.conftest import set_setting

    await set_setting(db_session, "security.admin_networks", [])
    superadmin = await make_user(db_session, SystemRole.SUPERADMIN)
    ad.add(superadmin.login)  # тот же логин в AD не мешает
    ad.available = False
    response = await _login(api, superadmin.login, PASSWORD)
    assert response.status_code == 200, response.text
    assert ad.calls == []


@pytest.mark.spec("FR-AUTH-AD-07")
async def test_roles_from_groups(
    api: httpx.AsyncClient, db_session: AsyncSession, fake_ad: FakeDirectory
) -> None:
    await complete_setup(db_session)
    sub = f"CN=Moderators Moscow,OU=Groups,{support.BASE}"
    fake_ad.nested[sub] = {support.MODERATORS}
    await support.configure(db_session, mapping=[(support.MODERATORS, "moderator"),
                                                 (support.PRESALES, "presale")])  # fmt: skip
    person = fake_ad.add("orlov", groups=(support.ACCESS, sub))
    assert (await _login(api, "orlov", person.password)).status_code == 200
    user = await _user(db_session, person)
    assert await _roles(db_session, user) == {"moderator": "ad_group"}, "вложенная группа даёт роль"

    db_session.add(UserRole(user_id=user.id, role=SystemRole.PRESALE, source=RoleSource.MANUAL))
    db_session.add(UserRole(user_id=user.id, role=SystemRole.PRESALE_HEAD,
                            source=RoleSource.MANUAL))  # fmt: skip
    await db_session.flush()
    person.groups = {support.ACCESS, support.PRESALES}
    api.cookies.clear()
    assert (await _login(api, "orlov", person.password)).status_code == 200
    assert await _roles(db_session, user) == {"presale": "ad_group", "presale_head": "manual"}
    changes = await _events(db_session, "users.roles.changed", user.id)
    assert changes[-1] == {"added": [], "removed": ["moderator"], "source": "ad_group"}


async def test_blocked_users(
    api: httpx.AsyncClient, db_session: AsyncSession, ad: FakeDirectory
) -> None:
    manual = ad.add("volkov")
    auto = ad.add("zaitsev")
    for person in (manual, auto):
        api.cookies.clear()
        assert (await _login(api, person.entry.login, person.password)).status_code == 200
    for person, reason in ((manual, UserBlockReason.MANUAL), (auto, UserBlockReason.AD_GROUP)):
        user = await _user(db_session, person)
        user.status, user.block_reason = UserStatus.BLOCKED, reason
    await db_session.flush()

    api.cookies.clear()
    assert (await _login(api, "volkov", manual.password)).status_code == 401
    assert (await _reasons(db_session, "volkov"))[-1] == "user_blocked"
    api.cookies.clear()
    assert (await _login(api, "zaitsev", auto.password)).status_code == 200
    unblocked = await _user(db_session, auto)
    assert unblocked.status is UserStatus.ACTIVE
    assert await _events(db_session, "users.unblocked", unblocked.id) == [
        {"previous_reason": "ad_group", "automatic": True}
    ]
