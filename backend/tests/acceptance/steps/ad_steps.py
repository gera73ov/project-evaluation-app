"""QA-012 · шаги сценариев AD (SPEC 17.2): G-04, G-05, G-06 «Аутентификация через AD», G-10,
G-11 «Смена режима входа», G-26 «Автоархивация и синхронизация AD».

Сценарии с тегом ``@samba`` идут против настоящего Samba AD DC (``make up-test && make
test-ad``), без него пропускаются. G-06 и G-11 Samba не нужен — они идут и в обычном CI.
Имена из текста сценариев (i.ivanov, p.sidorov, a.petrov) — псевдонимы: в Samba заводятся
уникальные учётки ``qa-ad-…``, чтобы прогоны и сценарии Playwright не мешали друг другу.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pyotp
import pytest
import yaml
from pytest_bdd import given, parsers, then, when
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_sync, switch_mode
from estimator.auth.providers import ldap
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.db.enums import SystemRole, UserBlockReason, UserStatus
from estimator.db.models.users import User
from estimator.jobs.schedule import build_beat_schedule
from estimator.security.crypto import get_cipher
from tests.acceptance.steps.common import aio, bdd_loop  # noqa: F401 — фикстура шагов
from tests.integration.adm.helpers import step_up
from tests.integration.auth.conftest import set_setting
from tests.integration.auth.helpers import PASSWORD, make_user
from tests.integration.core.conftest import Actor, World
from tests.support import fake_ad
from tests.support.samba import AdUser, Samba

LOGIN = "/api/v1/auth/login"
SWITCH = "/system/auth/switch-mode"
ERRORS = Path(__file__).resolve().parents[4] / "contracts" / "errors.yaml"


class Ctx:
    """Состояние сценария между шагами."""

    def __init__(self) -> None:
        self.people: dict[str, AdUser] = {}
        self.locals: dict[str, User] = {}
        self.responses: dict[str, httpx.Response] = {}
        self.cookies: httpx.Cookies | None = None
        self.root: Actor | None = None


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


@pytest.fixture(autouse=True)
def own_switch_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Решения и итог перехода — свои ключи Redis у каждого сценария."""
    tag = f"test:{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(switch_mode, "DECISIONS_KEY", f"{tag}:{switch_mode.DECISIONS_KEY}")
    monkeypatch.setattr(switch_mode, "LAST_KEY", f"{tag}:{switch_mode.LAST_KEY}")
    monkeypatch.setattr(ad_sync, "STATE_KEY", f"{tag}:{ad_sync.STATE_KEY}")


def _user_message_ad(code: str) -> str:
    errors = yaml.safe_load(ERRORS.read_text(encoding="utf-8"))
    items = errors["errors"] if isinstance(errors, dict) else errors
    return next(e["user_message_ad"] for e in items if e["code"] == code)


async def _login(world: World, login: str, password: str) -> httpx.Response:
    world.api.cookies.clear()
    return await world.api.post(LOGIN, json={"login": login, "password": password})


async def _reasons(db: AsyncSession, login: str) -> list[str]:
    rows = await db.execute(text(
        "SELECT details->>'reason' FROM audit.audit_log WHERE event_type = 'auth.login.failed' "
        "AND login = :l ORDER BY id"), {"l": login})  # fmt: skip
    return [r[0] for r in rows]


async def _root(world: World, ctx: Ctx) -> Actor:
    if ctx.root is None:
        ctx.root = await world.actor(SystemRole.SUPERADMIN)
        await step_up(world, ctx.root)
    return ctx.root


# --- Дано -------------------------------------------------------------------------------------


@given("выбран режим «Active Directory»")
@aio
async def ad_mode(world: World, db_session: AsyncSession, samba: Samba) -> None:
    await samba.configure(db_session)


@given(parsers.parse("у пользователя {alias} в AD установлен флаг ACCOUNTDISABLE"))
def disabled_in_ad(ctx: Ctx, samba: Samba, alias: str) -> None:
    ctx.people[alias] = samba.add_user(alias, disabled=True)


@given(parsers.parse("пользователь {alias} не состоит в группе доступа"))
def not_in_group(ctx: Ctx, samba: Samba, alias: str) -> None:
    ctx.people[alias] = samba.add_user(alias, groups=())


@given("все контроллеры AD недоступны")
@aio
async def ad_down(world: World, db_session: AsyncSession) -> None:
    await fake_ad.configure(db_session)
    await set_setting(db_session, ldap.CONNECTION, fake_ad.connection(
        controllers=[{"host": "127.0.0.1", "port": 1}, {"host": "127.0.0.1", "port": 9}],
        timeout_seconds=1,
    ))  # fmt: skip
    ldap.set_directory_factory(None)  # настоящий ldap3: соединение отклоняется


@given(parsers.parse("режим «Приложение» и локальный пользователь {alias}"))
@aio
async def local_mode_user(
    world: World, db_session: AsyncSession, samba: Samba, ctx: Ctx, alias: str
) -> None:
    await samba.configure(db_session, mode="local")
    user = await make_user(db_session)
    user.login, user.full_name = samba.name(alias), "Петров Андрей Сергеевич"
    await db_session.flush()
    ctx.locals[alias] = user


@given(parsers.parse("в AD есть учётка {alias}, но с другим ФИО"))
def same_login_other_name(ctx: Ctx, samba: Samba, alias: str) -> None:
    local = ctx.locals[alias]
    ctx.people[alias] = samba.add_user(login=local.login, full_name="Петров Алексей Викторович")


@given("режим «Active Directory»")
@aio
async def ad_mode_configured(world: World, db_session: AsyncSession) -> None:
    await fake_ad.configure(db_session, mode="ad")


@given("у пользователя открыта сессия")
@aio
async def open_session(world: World, db_session: AsyncSession, samba: Samba, ctx: Ctx) -> None:
    await samba.configure(db_session)
    person = samba.add_user("sess")
    ctx.people["user"] = person
    response = await _login(world, person.login, person.password)
    assert response.status_code == 200, response.text
    ctx.cookies = httpx.Cookies(world.api.cookies)
    assert (await world.api.get("/api/v1/me")).status_code == 200


# --- Когда ------------------------------------------------------------------------------------


@when(parsers.re(r"(?P<alias>\S+) вводит верный пароль( AD)?"))
@aio
async def enters_password(world: World, ctx: Ctx, samba: Samba, alias: str) -> None:
    person = ctx.people[alias]
    ctx.responses["login"] = await _login(world, person.login, person.password)
    # для сравнения «тем же сообщением»: заведомо неверный пароль существующей учётки
    probe = samba.add_user("probe")
    ctx.responses["wrong"] = await _login(world, probe.login, "Wrong-" + probe.password)


@when("суперадминистратор вводит пароль приложения и код TOTP")
@aio
async def superadmin_login(world: World, db_session: AsyncSession, ctx: Ctx) -> None:
    await set_setting(db_session, "security.admin_networks", [])
    root = await make_user(db_session, SystemRole.SUPERADMIN)
    secret = new_secret()
    root.totp_secret_enc = encrypt_secret(get_cipher(), root.id, secret)
    root.totp_enabled = True
    await db_session.flush()
    first = await _login(world, root.login, PASSWORD)
    assert first.status_code == 200, first.text
    assert first.json()["step"] == "totp"
    ctx.responses["login"] = await world.api.post("/api/v1/auth/totp", json={
        "login_token": first.json()["login_token"], "code": pyotp.TOTP(secret).now(),
    })  # fmt: skip


@when("суперадминистратор запускает переход в режиме dry run")
@aio
async def dry_run(world: World, ctx: Ctx) -> None:
    root = await _root(world, ctx)
    ctx.responses["dry"] = await root.post(SWITCH, json={"mode": "ad", "dry_run": True})


@when("суперадминистратор открывает раздел «Аутентификация»")
@aio
async def open_auth_section(world: World, ctx: Ctx) -> None:
    root = await _root(world, ctx)
    ctx.responses["section"] = await root.get("/system/settings/auth")


@when("его удалили из группы доступа AD")
@aio
async def removed_from_group(
    world: World, db_session: AsyncSession, redis_client: Redis, samba: Samba, ctx: Ctx
) -> None:
    from tests.support.samba import ACCESS

    person = ctx.people["user"]
    samba.remove_member(ACCESS, person.dn)
    # проверка, которую beat запускает каждые 15 минут (ad_sync_sessions)
    await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)


# --- То ---------------------------------------------------------------------------------------


@then(parsers.parse("вход отклоняется с сообщением «{message}»"))
def refused_with_message(ctx: Ctx, message: str) -> None:
    response = ctx.responses["login"]
    assert response.status_code == 401, response.text
    assert (response.json()["code"], response.json()["auth_mode"]) == ("LOGIN_FAILED", "ad")
    assert _user_message_ad("LOGIN_FAILED") == message, "текст сообщения в режиме AD"


@then("вход отклоняется тем же сообщением, что и при неверном пароле")
def refused_like_wrong_password(ctx: Ctx) -> None:
    response, wrong = ctx.responses["login"], ctx.responses["wrong"]
    assert response.status_code == wrong.status_code == 401
    same = ("code", "auth_mode", "title", "status")
    assert {k: response.json().get(k) for k in same} == {k: wrong.json().get(k) for k in same}


@then(parsers.parse("в аудите появляется событие login.failed с причиной {reason}"))
@aio
async def audited_reason(db_session: AsyncSession, ctx: Ctx, reason: str) -> None:
    [person] = ctx.people.values()
    assert (await _reasons(db_session, person.login))[-1] == reason


@then("вход выполняется успешно")
def logged_in(ctx: Ctx) -> None:
    response = ctx.responses["login"]
    assert response.status_code == 200, response.text
    assert response.json()["step"] == "done"


@then(parsers.parse("{alias} попадает в список «неоднозначно»"))
def in_ambiguous(ctx: Ctx, alias: str) -> None:
    response = ctx.responses["dry"]
    assert response.status_code == 200, response.text
    body = response.json()
    login = ctx.locals[alias].login
    assert login in [i["login"] for i in body["ambiguous"]]
    assert login not in [i["login"] for i in body["matched"]]
    assert body["applied"] is False


@then("переход нельзя применить, пока суперадминистратор не решит по каждому неоднозначному")
@aio
async def cannot_apply(world: World, db_session: AsyncSession, ctx: Ctx) -> None:
    from estimator.auth.policy import load_auth_mode

    root = await _root(world, ctx)
    applied = await root.post(SWITCH, json={"mode": "ad", "dry_run": False})
    assert (applied.status_code, applied.json()["code"]) == (409, "MODE_SWITCH_UNRESOLVED")
    assert await load_auth_mode(db_session) == "local"


@then("переключателя «Приложение» нет")
@aio
async def no_local_switch(world: World, db_session: AsyncSession, ctx: Ctx) -> None:
    """На уровне API: раздел отдаёт режим AD, а сменить его на «Приложение» настройкой нельзя
    (сам переключатель в интерфейсе проверяет Playwright, FE-094)."""
    from estimator.auth.policy import load_auth_mode

    section = ctx.responses["section"]
    assert section.status_code == 200, section.text
    assert section.json()["values"]["auth.mode"] == "ad"
    root = await _root(world, ctx)
    back = await root.put("/system/settings/auth", json={"values": {"auth.mode": "local"}})
    assert back.status_code in (409, 422), back.text
    assert await load_auth_mode(db_session) == "ad"


@then(parsers.parse("POST /system/auth/switch-mode с mode=local возвращает {status:d}"))
@aio
async def switch_back_refused(world: World, ctx: Ctx, status: int) -> None:
    root = await _root(world, ctx)
    for dry in (True, False):
        response = await root.post(SWITCH, json={"mode": "local", "dry_run": dry})
        assert (response.status_code, response.json()["code"]) == (
            status,
            "MODE_SWITCH_NOT_ALLOWED",
        )


@then("не позже чем через 15 минут сессия завершена")
@aio
async def session_ended(world: World, ctx: Ctx) -> None:
    schedule = build_beat_schedule()["ad_sync_sessions"]
    assert schedule["task"] == "estimator.auth.ad_sync.sessions"
    assert str(schedule["schedule"]._orig_minute) == "*/15", "проверка сессий раз в 15 минут"
    assert ctx.cookies is not None
    world.api.cookies = ctx.cookies
    assert (await world.api.get("/api/v1/me")).status_code == 401


@then(parsers.parse("пользователь заблокирован с причиной {reason}"))
@aio
async def blocked_with(db_session: AsyncSession, ctx: Ctx, reason: str) -> None:
    person = ctx.people["user"]
    user = await db_session.scalar(select(User).where(User.ad_object_guid == person.object_guid)
                                   .execution_options(populate_existing=True))  # fmt: skip
    assert user is not None
    assert (user.status, user.block_reason) == (UserStatus.BLOCKED, UserBlockReason(reason))
