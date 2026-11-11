"""ADM-001: мастер первичной настройки — полное прохождение в режиме «Приложение», режим AD до
проверок AD и после них (FE-094), повтор после завершения (7.1, FR-SA-02, SEC-AUD-01)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.setup_gate import setup_completed
from estimator.db.enums import SystemRole
from estimator.notifications import tasks as mail_tasks
from estimator.security.crypto import get_cipher
from tests.integration.adm.helpers import audit_details
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import Actor, World

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.1"), pytest.mark.spec("FR-SA-02")]

SERVER = {"host": "smtp.corp", "port": 587, "security": "starttls", "username": None,
          "from_address": "robot@corp.ru", "from_name": "Оценка проектов",
          "timeout_seconds": 10}  # fmt: skip
POLICY = {"min_length": 14, "max_length": 128, "check_common_passwords": True,
          "forbid_personal_data": True, "history": 5, "expiry_days": None,
          "require_uppercase": False, "require_digit": False, "require_special": False,
          "max_sessions": None}  # fmt: skip


@pytest.fixture
async def fresh(world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> World:
    """Мастер не пройден (фикстура ``world`` его завершает); письма не уходят в брокер."""
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: None)
    await set_setting(db_session, "app.setup", {"completed_at": None, "steps_done": []})
    return world


async def _post(root: Actor, step: str, values: dict[str, Any], **kw: Any) -> Any:
    return await root.post(f"/system/setup/{step}", json={"values": values, **kw})


async def test_full_wizard_local_mode(fresh: World, db_session: AsyncSession) -> None:
    root = await fresh.actor(SystemRole.SUPERADMIN)
    assert not await setup_completed(db_session)  # «Приложение настраивается» (AUTH-012)

    first = await root.get("/system/setup/app")
    assert first.status_code == 200, first.text
    assert (first.json()["done"], first.json()["values"]["app.timezone"]) == (
        False,
        "Europe/Moscow",
    )
    no_url = await _post(root, "app", {"app.timezone": "Europe/Samara"})
    assert (no_url.status_code, no_url.json()["code"]) == (422, "VALIDATION_FAILED")
    step1 = await _post(
        root, "app", {"app.base_url": "https://est.corp", "app.timezone": "Europe/Samara"}
    )
    assert step1.status_code == 200, step1.text
    assert step1.json()["done"] is True

    early = await _post(root, "smtp", {"smtp.server": SERVER}, complete=True)
    assert (early.status_code, early.json()["code"]) == (422, "VALIDATION_FAILED")  # не все шаги
    step2 = await _post(root, "smtp", {"smtp.server": SERVER, "smtp.password": "pw"})
    assert step2.json()["values"]["smtp.password"] == {"set": True}
    wrong = await _post(root, "smtp", {"security.lockout": {"max_failures": 5, "lock_minutes": 15}})
    assert wrong.status_code == 422
    ad = await _post(root, "auth", {"auth.mode": "ad"})
    assert (ad.status_code, ad.json()["code"]) == (409, "AD_CHECKS_REQUIRED")  # проверок AD не было
    step3 = await _post(root, "auth", {"auth.mode": "local", "security.password_policy": POLICY})
    assert step3.status_code == 200, step3.text
    assert step3.json()["values"]["security.password_policy"]["min_length"] == 14
    step4 = await _post(
        root, "security", {"security.lockout": {"max_failures": 6, "lock_minutes": 20}}
    )
    assert step4.status_code == 200, step4.text

    nobody = await _post(root, "first_admin", {})
    assert nobody.status_code == 422  # нет ни одного администратора
    tag = uuid.uuid4().hex[:8]
    admin = {"login": f"adm.{tag}", "email": f"{tag}@corp.ru", "full_name": "Первый Админ"}
    in_ad = await _post(root, "first_admin", {**admin, "ad_object_guid": str(uuid.uuid4())})
    assert in_ad.status_code == 422  # из каталога AD — только в режиме AD
    step5 = await _post(root, "first_admin", admin, complete=True)
    assert step5.status_code == 200, step5.text
    values = step5.json()["values"]
    assert values["activation"]["emailed"] is True  # SMTP уже настроен шагом 2
    assert [a["login"] for a in values["admins"]] == [admin["login"]]

    assert await setup_completed(db_session)  # режим «Приложение настраивается» снят
    again = await _post(root, "app", {"app.timezone": "Europe/Moscow"})
    assert (again.status_code, again.json()["code"]) == (409, "SETUP_ALREADY_COMPLETED")
    assert (await root.get("/system/setup/first_admin")).json()["done"] is True

    steps = [d["step"] for d in await audit_details(db_session, "system.setup.step_completed")]
    assert steps == ["address_timezone", "smtp", "auth_mode", "security_policies", "first_admin"]
    assert len(await audit_details(db_session, "system.setup.finished")) == 1


async def test_wizard_access(fresh: World) -> None:
    root = await fresh.actor(SystemRole.SUPERADMIN)
    assert (await root.get("/system/setup/unknown")).status_code == 404


async def test_only_superadmin(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    assert (await admin.get("/system/setup/app")).status_code == 403


async def _verify(db: AsyncSession) -> None:
    """Обе проверки AD прошли с сохранёнными параметрами (как после «Проверить …»)."""
    import datetime as dt

    from estimator.auth.providers import ldap

    values, password = await ldap.stored_values(db)
    now = dt.datetime.now(dt.UTC).isoformat()
    await set_setting(db, "auth.ad.verification", {
        "params_sha256": ldap.fingerprint(values, password),
        "connection_ok_at": now, "login_ok_at": now,
    })  # fmt: skip


async def test_wizard_ad_mode(fresh: World, db_session: AsyncSession) -> None:
    from estimator.auth.policy import load_auth_mode
    from estimator.auth.providers import ldap
    from tests.support import fake_ad

    root = await fresh.actor(SystemRole.SUPERADMIN)
    await set_setting(db_session, ldap.CONNECTION, fake_ad.connection())
    password = fake_ad.new_password()
    ad_values = {ldap.BIND_PASSWORD: password, ldap.ACCESS_GROUPS: [fake_ad.ACCESS]}

    unchecked = await _post(root, "auth", {"auth.mode": "ad", **ad_values})
    assert (unchecked.status_code, unchecked.json()["code"]) == (409, "AD_CHECKS_REQUIRED")
    assert await load_auth_mode(db_session) == "local"

    for key, value in ad_values.items():
        stored = get_cipher().encrypt_setting(key, value) if key == ldap.BIND_PASSWORD else value
        await set_setting(db_session, key, stored)
    await _verify(db_session)
    policy = await _post(root, "auth", {"auth.mode": "ad", "security.password_policy": POLICY})
    assert policy.status_code == 422  # политика паролей — только для «Приложения»

    step = await _post(root, "auth", {"auth.mode": "ad"})
    assert step.status_code == 200, step.text
    assert step.json()["done"] is True
    assert await load_auth_mode(db_session) == "ad"
    again = await _post(root, "auth", {"auth.mode": "ad"})  # шаг можно сохранить ещё раз
    assert again.status_code == 200, again.text
    switched = await audit_details(db_session, "system.auth_mode.switched")
    assert [(d["to"], d["via"]) for d in switched] == [("ad", "ui")]

    back = await _post(root, "auth", {"auth.mode": "local", "security.password_policy": POLICY})
    assert back.status_code == 200, back.text  # учёток из AD ещё нет — можно вернуться
    assert await load_auth_mode(db_session) == "local"

    await fresh.actor(SystemRole.MODERATOR)  # появилась локальная учётка — нужен отчёт перехода
    blocked = await _post(root, "auth", {"auth.mode": "ad"})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["errors"][0]["field"] == "/values/auth.mode"
