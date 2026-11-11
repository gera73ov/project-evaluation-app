"""QA-012 · вход через AD на настоящем контроллере Samba AD DC (TC-AUTH-01; FR-AUTH-AD-01, -02,
-05, -06, -07, -09, -13; AUTH-013, AUTH-014, AUTH-015, AUTH-017).

Те же проверки, что ``tests/integration/auth/test_ad_login.py`` на имитации, но против LDAP
настоящего AD: экранирование фильтра, bind, ``userAccountControl``, вложенность групп через
``LDAP_MATCHING_RULE_IN_CHAIN``, objectGUID при переименовании, проверка сертификата
контроллера. Запуск: ``make up-test && make test-ad``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers import base, ldap
from estimator.auth.providers.ldap import AdConfig, Entry, Ldap3Directory
from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from tests.integration.adm.helpers import step_up
from tests.integration.core.conftest import World
from tests.support import samba as ad
from tests.support.samba import AdUser, Samba

pytestmark = [pytest.mark.integration, pytest.mark.samba, pytest.mark.tc("TC-AUTH-01"),
              pytest.mark.spec("FR-AUTH-AD-13")]  # fmt: skip

LOGIN = "/api/v1/auth/login"
SAME_ANSWER = {"code": "LOGIN_FAILED", "auth_mode": "ad"}


class Counting:
    """Настоящий каталог ``ldap3`` с журналом вызовов (сколько раз приложение шло в AD)."""

    calls: list[str]

    def __init__(self, inner: Ldap3Directory, calls: list[str]) -> None:
        self.inner, self.calls = inner, calls

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.inner, name)

        async def call(*args: Any) -> Any:
            self.calls.append(name)
            return await method(*args)

        return call


@pytest.fixture
def calls() -> list[str]:
    journal: list[str] = []
    ldap.set_directory_factory(lambda config: Counting(Ldap3Directory(config), journal))  # type: ignore[arg-type,return-value]
    yield journal
    ldap.set_directory_factory(None)


@pytest.fixture
async def on_samba(world: World, db_session: AsyncSession, samba: Samba) -> Samba:
    await samba.configure(db_session)
    return samba


async def _login(api: httpx.AsyncClient, login: str, password: str) -> httpx.Response:
    api.cookies.clear()
    return await api.post(LOGIN, json={"login": login, "password": password})


async def _reasons(db: AsyncSession, login: str) -> list[str]:
    rows = await db.execute(text(
        "SELECT details->>'reason' FROM audit.audit_log WHERE event_type = 'auth.login.failed' "
        "AND login = :l ORDER BY id"), {"l": login})  # fmt: skip
    return [r[0] for r in rows]


async def _user(db: AsyncSession, person: AdUser) -> User | None:
    return await db.scalar(
        select(User).where(User.ad_object_guid == person.object_guid)
        .execution_options(populate_existing=True)
    )  # fmt: skip


async def _roles(db: AsyncSession, user: User) -> dict[str, str]:
    rows = await db.execute(
        select(UserRole.role, UserRole.source).where(UserRole.user_id == user.id)
    )
    return {SystemRole(r).value: RoleSource(s).value for r, s in rows.all()}


def _answer(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    return {"code": body["code"], "auth_mode": body.get("auth_mode")}


def _foreign_ca() -> str:
    """Самоподписанный УЦ, которым сертификат контроллера НЕ выпущен."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "QA foreign CA")])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))  # fmt: skip
    return cert.public_bytes(serialization.Encoding.PEM).decode()


# --- TC-AUTH-01 ---------------------------------------------------------------------------------


async def test_empty_password_rejected_without_bind(
    world: World, db_session: AsyncSession, on_samba: Samba, calls: list[str]
) -> None:
    person = on_samba.add_user("empty")
    response = await _login(world.api, person.login, "")
    assert response.status_code == 422, "пустой пароль отклоняется схемой запроса"
    result = await base.authenticate(db_session, "ad", base.Credentials(person.login, ""))
    assert result.reason == "empty_credentials"
    blank = await base.authenticate(db_session, "ad", base.Credentials("  ", "x"))
    assert blank.reason == "empty_credentials"
    assert calls == [], "ни поиска, ни bind в AD"


async def test_ldap_injection_is_escaped(
    world: World, db_session: AsyncSession, on_samba: Samba, calls: list[str]
) -> None:
    on_samba.add_user("inj")
    for login in ("*)(uid=*", "*", f"{ad.PREFIX}*", "*)(objectClass=*", "x)(|(sAMAccountName=*"):
        response = await _login(world.api, login, "Whatever-1!")
        assert response.status_code == 401, (login, response.text)
        assert _answer(response) == SAME_ANSWER
        assert (await _reasons(db_session, login))[-1] == "user_not_found", login
    assert "find_user" in calls, "фильтр ушёл в AD экранированным"
    assert "check_password" in calls, "bind и для ненайденного логина"


@pytest.mark.spec("FR-AUTH-AD-05")
@pytest.mark.gherkin("G-04")
@pytest.mark.gherkin("G-05")
async def test_refusals_are_uniform_and_reasons_audited(
    world: World, db_session: AsyncSession, on_samba: Samba
) -> None:
    ok = on_samba.add_user("ok")
    disabled = on_samba.add_user("off", disabled=True)
    outsider = on_samba.add_user("out", groups=())
    seeded_outsider = "no.access"  # seed.sh: только в est-unrelated
    cases = [
        (ok.login, "Wrong-" + ok.password, "wrong_password"),
        (disabled.login, disabled.password, "ad_account_disabled"),
        (disabled.login, "Wrong-" + disabled.password, "wrong_password"),
        (outsider.login, outsider.password, "ad_not_in_group"),
        (seeded_outsider, on_samba.env.service_password, "ad_not_in_group"),
        (on_samba.name("none"), "Whatever-1!", "user_not_found"),
    ]
    answers = set()
    for login, password, reason in cases:
        response = await _login(world.api, login, password)
        assert response.status_code == 401, (login, response.text)
        answers.add(tuple(_answer(response).items()))
        assert (await _reasons(db_session, login))[-1] == reason, login
    assert answers == {tuple(SAME_ANSWER.items())}, "один и тот же ответ на любой отказ"
    for person in (disabled, outsider):
        assert await _user(db_session, person) is None, "без проверок AD учётка не создаётся"


async def test_ambiguous_filter_match(world: World, db_session: AsyncSession, samba: Samba) -> None:
    """Фильтр входа нашёл две записи (вход по общему email) — отказ ``ad_ambiguous``."""
    mail = f"{samba.name('mail')}@test.estimator.local"
    first = samba.add_user("twa", mail=mail)
    samba.add_user("twb", mail=mail)
    await samba.configure(
        db_session, user_filter="(&(objectClass=user)(|(sAMAccountName={login})(mail={login})))"
    )
    response = await _login(world.api, mail, first.password)
    assert (response.status_code, _answer(response)) == (401, SAME_ANSWER)
    assert (await _reasons(db_session, mail))[-1] == "ad_ambiguous"
    alone = await _login(world.api, first.login, first.password)
    assert alone.status_code == 200, "по логину запись одна"


# --- вход, вложенные группы, переименование, роли -----------------------------------------------


@pytest.mark.spec("FR-AUTH-AD-06")
async def test_first_login_creates_user_and_rename_keeps_it(
    world: World, db_session: AsyncSession, on_samba: Samba
) -> None:
    person = on_samba.add_user("ren", full_name="Переименов Иван")
    response = await _login(world.api, person.login, person.password)
    assert response.status_code == 200, response.text
    assert response.json()["step"] == "done"
    user = await _user(db_session, person)
    assert user is not None
    assert (user.source, user.status, user.full_name, user.email) == (
        UserSource.AD, UserStatus.ACTIVE, "Переименов Иван", f"{person.login}@test.estimator.local"
    )  # fmt: skip
    assert user.password_hash is None

    new_login = on_samba.name("new")
    on_samba.rename(person, new_login, full_name="Переименов Иван Иванович")
    old = await _login(world.api, user.login, person.password)
    assert old.status_code == 401, "старый логин больше не входит"
    again = await _login(world.api, new_login, person.password)
    assert again.status_code == 200, again.text
    renamed = await _user(db_session, person)
    assert renamed is not None
    assert (renamed.id, renamed.login, renamed.full_name) == (
        user.id,
        new_login,
        "Переименов Иван Иванович",
    ), "тот же objectGUID — та же учётка"


async def test_nested_groups_give_access(
    world: World, db_session: AsyncSession, on_samba: Samba
) -> None:
    team = on_samba.add_group("team", member_of=[ad.EXPERTS])  # team ⊂ est-experts ⊂ est-access
    deep = on_samba.add_user("deep", groups=[team])
    assert (await _login(world.api, deep.login, deep.password)).status_code == 200
    seeded = await _login(world.api, "expert.nested", on_samba.env.service_password)
    assert seeded.status_code == 200, "seed.sh: est-presale-team ⊂ est-experts ⊂ est-access"


@pytest.mark.spec("FR-AUTH-AD-07")
async def test_roles_from_nested_groups(
    world: World, db_session: AsyncSession, samba: Samba
) -> None:
    await samba.configure(db_session, mapping=[(ad.MODERATORS, "moderator"),
                                               (ad.PRESALE_LEADS, "presale")])  # fmt: skip
    region = samba.add_group("modreg", member_of=[ad.MODERATORS])
    person = samba.add_user("role", groups=[ad.ACCESS, region])
    assert (await _login(world.api, person.login, person.password)).status_code == 200
    user = await _user(db_session, person)
    assert user is not None
    assert await _roles(db_session, user) == {"moderator": "ad_group"}

    samba.remove_member(region, person.dn)
    samba.add_member(ad.PRESALE_LEADS, person.dn)
    assert (await _login(world.api, person.login, person.password)).status_code == 200
    assert await _roles(db_session, user) == {"presale": "ad_group"}


# --- подключение: TLS, StartTLS, недоступность --------------------------------------------------


@pytest.mark.spec("FR-AUTH-AD-02")
async def test_starttls_on_389(world: World, db_session: AsyncSession, samba: Samba) -> None:
    await samba.configure(db_session, protocol="starttls")
    person = samba.add_user("stls")
    assert (await _login(world.api, person.login, person.password)).status_code == 200


@pytest.mark.spec("FR-AUTH-AD-02")
@pytest.mark.parametrize("protocol", ["ldaps", "starttls"])
@pytest.mark.parametrize("ca", ["foreign", "system"])
async def test_untrusted_controller_certificate_rejected(
    world: World, db_session: AsyncSession, samba: Samba, protocol: str, ca: str
) -> None:
    """Сертификат контроллера не от указанного УЦ (или УЦ не указан, а dev-УЦ не в системных
    доверенных) — соединение не устанавливается, вход отвечает 503."""
    await samba.configure(db_session, protocol=protocol,
                          ca_pem=_foreign_ca() if ca == "foreign" else None)  # fmt: skip
    person = samba.add_user("tls")
    response = await _login(world.api, person.login, person.password)
    assert (response.status_code, response.json()["code"]) == (503, "AUTH_SERVICE_UNAVAILABLE")
    assert await _reasons(db_session, person.login) == ["ad_unavailable"]


@pytest.mark.spec("FR-AUTH-AD-09")
async def test_second_controller_used_when_first_down(
    world: World, db_session: AsyncSession, samba: Samba
) -> None:
    env = samba.env
    await samba.configure(
        db_session,
        controllers=[{"host": env.host, "port": 1}, {"host": env.host, "port": env.ldaps_port}],
    )
    person = samba.add_user("dc2")
    assert (await _login(world.api, person.login, person.password)).status_code == 200


# --- проверки настроек и поиск в каталоге (AUTH-015, AUTH-017) ----------------------------------


def _form(samba: Samba, **conn: Any) -> dict[str, Any]:
    return {ldap.CONNECTION: samba.connection(**conn), ldap.BIND_PASSWORD:
            samba.env.service_password, ldap.ACCESS_GROUPS: [ad.ACCESS]}  # fmt: skip


@pytest.mark.spec("FR-AUTH-AD-03")
async def test_settings_checks_against_samba(
    world: World, db_session: AsyncSession, samba: Samba
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    person = samba.add_user("chk", full_name="Проверкин Пётр")
    form = _form(samba)

    connected = await root.post("/system/auth/ad/test-connection", json={"values": form})
    assert (connected.status_code, connected.json()["ok"]) == (200, True), connected.text
    foreign = await root.post("/system/auth/ad/test-connection",
                              json={"values": _form(samba, ca_pem=_foreign_ca())})  # fmt: skip
    assert foreign.json()["ok"] is False, "чужой УЦ — проверка подключения не проходит"
    bad_bind = {**form, ldap.BIND_PASSWORD: "Wrong-" + samba.env.service_password}
    refused = await root.post("/system/auth/ad/test-connection", json={"values": bad_bind})
    assert refused.json()["ok"] is False, "неверный пароль сервисной учётки"

    path = "/system/auth/ad/test-login"
    wrong = await root.post(path, json={"values": form, "login": person.login,
                                        "password": "Wrong-1!"})  # fmt: skip
    assert wrong.json()["ok"] is False
    logged = await root.post(path, json={"values": form, "login": person.login,
                                         "password": person.password})  # fmt: skip
    assert logged.status_code == 200, logged.text
    assert logged.json()["ok"] is True
    assert logged.json()["user"]["full_name"] == "Проверкин Пётр"

    saved = await root.put("/system/settings/auth", json={"values": form})
    assert saved.status_code == 200, saved.text


async def test_directory_search_on_samba(
    world: World, db_session: AsyncSession, on_samba: Samba
) -> None:
    inside = on_samba.add_user("srch", full_name="Искомова Анна")
    outside = on_samba.add_user("srcx", full_name="Искомова Вера", groups=())
    admin = await world.actor(SystemRole.ADMIN)
    found = await admin.get("/admin/ad/search", params={"q": "Искомова"})
    assert found.status_code == 200, found.text
    items = {i["login"]: i for i in found.json()["items"]}
    assert items[inside.login]["in_access_group"] is True
    assert items[outside.login]["in_access_group"] is False


# --- каталог напрямую: те же записи, что видит приложение ---------------------------------------


async def _verify(
    samba: Samba, login: str, password: str, groups: Sequence[str] = (ad.ACCESS,)
) -> tuple[str | None, Entry | None]:
    conn = samba.connection()
    values = {ldap.CONNECTION: conn, ldap.ACCESS_GROUPS: list(groups)}
    config = AdConfig.from_values(values, samba.env.service_password)
    verdict = await ldap.verify(Ldap3Directory(config), config, login, password)
    return verdict.reason, verdict.entry


async def test_seeded_directory_as_documented(samba: Samba) -> None:
    """Учётки deploy/samba-ad/seed.sh такие, как описано в его шапке (на них опираются e2e)."""
    password = samba.env.service_password
    assert (await _verify(samba, "expert.one", password))[0] is None
    assert (await _verify(samba, "moderator.one", password))[0] is None
    assert (await _verify(samba, "disabled.one", password))[0] == "ad_account_disabled"
    assert (await _verify(samba, "no.access", password))[0] == "ad_not_in_group"
    _reason, entry = await _verify(samba, "expert.one", password)
    assert entry is not None
    assert entry.full_name == "Expert One"
