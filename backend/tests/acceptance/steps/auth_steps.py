"""QA-013 · шаги сценариев входа и ролей (SPEC 17.2): G-08 «Нельзя разжаловать последнего
суперадминистратора», G-09 «Нельзя удалить последнего модератора проекта», G-12 «Блокировка
после 5 попыток», G-19 «Модератор без TOTP в сессии».

Баннер админки и блок «Деньги» рисует интерфейс (QA-018) по ответам API, которые проверяются здесь.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pyotp
import yaml
from pytest_bdd import given, parsers, then, when
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.sessions import COOKIE_NAME
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.db.enums import SystemRole
from estimator.db.models.users import User
from estimator.security.crypto import get_cipher
from estimator.security.web.csrf import CSRF_COOKIE, CSRF_HEADER
from tests.acceptance.steps.ad_steps import Ctx
from tests.acceptance.steps.common import Scene, aio
from tests.integration.adm.helpers import step_up
from tests.integration.auth.conftest import set_setting
from tests.integration.auth.helpers import PASSWORD, make_user
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import create_project

ERRORS = Path(__file__).resolve().parents[4] / "contracts" / "errors.yaml"
LOGIN = "/api/v1/auth/login"


def _error(code: str) -> dict:
    errors = yaml.safe_load(ERRORS.read_text(encoding="utf-8"))
    items = errors["errors"] if isinstance(errors, dict) else errors
    return next(e for e in items if e["code"] == code)


def _client(world: World, ip: str) -> httpx.AsyncClient:
    """Клиент того же приложения с другого адреса (адрес — из транспорта, как у nginx)."""
    app = world.api.app  # type: ignore[attr-defined]
    transport = httpx.ASGITransport(app=app, client=(ip, 1))
    return httpx.AsyncClient(transport=transport, base_url="https://test")


# --- G-08: последний суперадминистратор ---------------------------------------------------------


@given("в системе один активный суперадминистратор")
@aio
async def sole_superadmin(world: World, db_session: AsyncSession, scene: Scene) -> None:
    await db_session.execute(text("DELETE FROM user_roles WHERE role = 'superadmin'"))
    await set_setting(db_session, "security.admin_networks", [])
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    scene.data["root"] = root


@when("он пытается заблокировать себя через API")
@aio
async def block_self(scene: Scene) -> None:
    root: Actor = scene.data["root"]
    scene.responses["block"] = await root.patch(
        f"/system/admins/{root.id}", json={"status": "blocked"}
    )
    scene.responses["demote"] = await root.delete(f"/system/admins/{root.id}")


@then(parsers.parse("ответ 409 с кодом {code}"))
def conflict_code(scene: Scene, code: str) -> None:
    for name in ("block", "demote", "remove", "head_remove"):
        response = scene.responses.get(name)
        if response is not None:
            assert (response.status_code, response.json()["code"]) == (409, code), name


@then(parsers.parse("в админке виден баннер «{text}»"))
@aio
async def sole_superadmin_banner(scene: Scene, text: str) -> None:
    """Баннер показывается, пока в списке ровно один активный суперадминистратор (FE-094)."""
    root: Actor = scene.data["root"]
    listed = await root.get("/system/admins")
    assert listed.status_code == 200, listed.text
    active = [a for a in listed.json()["items"]
              if a["status"] == "active" and "superadmin" in a["roles"]]  # fmt: skip
    assert [a["id"] for a in active] == [str(root.id)]
    i18n = Path(ERRORS).parents[1] / "frontend" / "src" / "shared" / "i18n" / "ru.json"
    assert text in i18n.read_text(encoding="utf-8")


# --- G-09: последний модератор проекта ----------------------------------------------------------


@given("в проекте «Портал дилеров» один модератор")
@aio
async def sole_moderator(world: World, scene: Scene) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    scene.data |= {"moderator": moderator, "pid": await create_project(world, moderator)}


@when("модератор (или руководитель пресейла, ставший модератором) удаляет его из команды")
@aio
async def remove_last_moderator(world: World, scene: Scene) -> None:
    moderator: Actor = scene.data["moderator"]
    pid = scene.data["pid"]
    url = f"/projects/{pid}/members"
    scene.responses["remove"] = await moderator.put(url, json={"members": []})
    # руководитель пресейла стал модератором и остался единственным после ухода первого
    head = await world.actor(SystemRole.PRESALE_HEAD)
    joined = await head.post(f"/projects/{pid}/join-as-moderator")
    assert joined.status_code == 200, joined.text
    team = {"members": [{"user_id": str(head.id), "role": "moderator"}]}
    left = await moderator.put(url, json=team)  # первый модератор уходит сам
    assert left.status_code == 200, left.text
    scene.responses["head_remove"] = await head.put(url, json={"members": []})


# --- G-12: блокировка пары «логин + IP» ---------------------------------------------------------


@given(parsers.parse("режим «Приложение» и пользователь {alias}"))
@aio
async def local_user(world: World, db_session: AsyncSession, scene: Scene, alias: str) -> None:
    user = await make_user(db_session)
    user.login = f"{alias}.{uuid.uuid4().hex[:6]}"  # ключи блокировок в Redis — свои у прогона
    await db_session.flush()
    scene.data["user"] = user


@when(parsers.parse("с адреса {ip} 5 раз подряд введён неверный пароль"))
@aio
async def five_failures(world: World, scene: Scene, ip: str) -> None:
    login = scene.data["user"].login
    async with _client(world, ip) as client:
        for _ in range(5):
            wrong = await client.post(LOGIN, json={"login": login, "password": "Wrong-1"})
            assert wrong.status_code == 401, wrong.text


@then(parsers.parse("шестая попытка с верным паролем с адреса {ip} отклоняется «{message}»"))
@aio
async def sixth_refused(world: World, scene: Scene, ip: str, message: str) -> None:
    async with _client(world, ip) as client:
        locked = await client.post(LOGIN, json={"login": scene.data["user"].login,
                                                "password": PASSWORD})  # fmt: skip
    assert (locked.status_code, locked.json()["code"]) == (429, "LOGIN_LOCKED")
    assert int(locked.headers["Retry-After"]) > 0
    assert _error("LOGIN_LOCKED")["user_message"] == message


@then("в аудите есть событие блокировки пары «логин + IP»")
@aio
async def pair_locked_audited(db_session: AsyncSession, scene: Scene) -> None:
    rows = await db_session.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = 'auth.lockout.pair_locked' "
        "AND login = :l"), {"l": scene.data["user"].login})  # fmt: skip
    assert [r[0] for r in rows] == [{"failures": 5, "minutes": 15, "actor": "system"}]


@when(parsers.parse("{alias} входит с верным паролем со своего адреса {ip}"))
@aio
async def login_from_other_ip(world: World, scene: Scene, ctx: Ctx, alias: str, ip: str) -> None:
    async with _client(world, ip) as client:
        ctx.responses["login"] = await client.post(
            LOGIN, json={"login": scene.data["user"].login, "password": PASSWORD}
        )


# --- G-19: деньги только после TOTP -------------------------------------------------------------


@given(parsers.parse(
    "политика TOTP для роли «Модератор» включена, пока пользователь {alias} в системе"
))  # fmt: skip
@aio
async def totp_policy_enabled(
    world: World, db_session: AsyncSession, scene: Scene, alias: str
) -> None:
    owner = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, owner)
    secret = new_secret()
    user = await db_session.get(User, owner.id)
    assert user is not None
    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, secret)
    user.totp_enabled = True
    await db_session.flush()
    # вошла, когда TOTP модератору был необязателен: в сессии второго фактора нет
    await set_setting(db_session, "security.mfa_policy", {"moderator": "optional"})
    session = await world.session_for(owner.id, SystemRole.MODERATOR, mfa=False)
    await set_setting(db_session, "security.mfa_policy", {"moderator": "required"})
    scene.data |= {"actor": session, "pid": pid, "secret": secret}


@when(parsers.parse("{alias} открывает настройки проекта"))
@aio
async def opens_settings(scene: Scene, alias: str) -> None:
    actor: Actor = scene.data["actor"]
    scene.responses["project"] = await actor.get(f"/projects/{scene.data['pid']}")
    scene.responses["money"] = await actor.get(f"/projects/{scene.data['pid']}/money")


@then(parsers.parse("блок «Деньги» показывает «🔒 {message}»"))
def money_locked(scene: Scene, message: str) -> None:
    assert scene.responses["project"].status_code == 200, scene.responses["project"].text
    problem = scene.responses["money"].json()
    assert (problem["code"], problem["title"]) == ("TOTP_REQUIRED", message)


@then(parsers.parse("GET /projects/{{id}}/money возвращает {status:d} {code}"))
def money_status(scene: Scene, status: int, code: str) -> None:
    response = scene.responses["money"]
    assert (response.status_code, response.json()["code"]) == (status, code)


@when("она вводит код TOTP")
@aio
async def enters_totp(world: World, scene: Scene) -> None:
    actor: Actor = scene.data["actor"]
    client = world.api
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, actor.sid)
    passed = await client.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(scene.data["secret"]).now(), "totp_only": True},
        headers={CSRF_HEADER: actor.csrf},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["mfa_passed"] is True
    # сессия сменила идентификатор (FR-SESS-03): дальше — с новой cookie и CSRF
    sid = passed.cookies.get(COOKIE_NAME) or client.cookies.get(COOKIE_NAME)
    csrf = passed.cookies.get(CSRF_COOKIE) or client.cookies.get(CSRF_COOKIE)
    assert sid
    assert csrf
    renewed = Actor(world, actor.id, sid, csrf)
    scene.responses["money"] = await renewed.get(f"/projects/{scene.data['pid']}/money")


@then("блок «Деньги» показывает ставки")
def money_rates(scene: Scene) -> None:
    response = scene.responses["money"]
    assert response.status_code == 200, response.text
    assert {"rates", "currency", "exchange_rate"} <= response.json().keys()
