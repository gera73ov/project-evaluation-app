"""ADM-002: системные настройки суперадминистратора и тестовое письмо (7.1, FR-AUTH-LOC-02,
FR-SA-04, FR-SA-06, NFR-REL-06, SEC-AUTH-05, SEC-AUTH-07, CR-009)."""

from __future__ import annotations

import smtplib
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.settings import SystemSetting
from estimator.notifications import mail
from estimator.notifications import tasks as mail_tasks
from estimator.security.alerts import notify
from tests.integration.adm.helpers import audit_details, step_up
from tests.integration.auth.conftest import set_setting
from tests.integration.auth.helpers import make_user
from tests.integration.core.conftest import World

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.1")]

SERVER = {
    "host": "smtp.corp",
    "port": 587,
    "security": "starttls",
    "username": "robot",
    "from_address": "robot@corp.ru",
    "from_name": "Оценка проектов",
    "timeout_seconds": 10,
}


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


async def _stored(db: AsyncSession, key: str) -> Any:
    return await db.scalar(select(SystemSetting.value).where(SystemSetting.key == key))


async def test_read_defaults_and_permissions(world: World) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    security = await root.get("/system/settings/security")
    assert security.status_code == 200, security.text
    values = security.json()["values"]
    assert values["security.lockout"] == {"max_failures": 5, "lock_minutes": 15}
    assert values["security.mfa_policy"]["admin"] == "required"
    assert set(values) == {
        "security.password_policy", "security.session", "security.lockout",
        "security.mfa_policy", "security.admin_networks", "security.alert_email",
    }  # fmt: skip
    smtp = (await root.get("/system/settings/smtp")).json()["values"]
    assert smtp["smtp.password"] == {"set": False}
    app = (await root.get("/system/settings/app")).json()
    assert set(app["values"]) == {"app.base_url", "app.timezone"}
    assert (await root.get("/system/settings/method")).status_code == 404
    admin = await world.actor(SystemRole.ADMIN)
    assert (await admin.get("/system/settings/security")).status_code == 403


@pytest.mark.spec("SEC-AUTH-05")
@pytest.mark.spec("FR-SA-04")
async def test_security_write_needs_step_up_and_is_audited(
    world: World, db_session: AsyncSession
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    body = {"values": {"security.lockout": {"max_failures": 7, "lock_minutes": 30}}}
    denied = await root.put("/system/settings/security", json=body)
    assert (denied.status_code, denied.json()["code"]) == (403, "STEP_UP_REQUIRED")
    await step_up(world, root)
    saved = await root.put("/system/settings/security", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["security.lockout"]["max_failures"] == 7
    again = await root.put("/system/settings/security", json=body)  # без изменений — без аудита
    assert again.status_code == 200
    mfa = {"admin": "optional", "moderator": "required", "presale": "required",
           "presale_head": "required", "security_auditor": "required",
           "user": "optional"}  # fmt: skip
    nets = ["10.0.0.0/8"]
    both = await root.put(
        "/system/settings/security",
        json={"values": {"security.mfa_policy": mfa, "security.admin_networks": nets}},
    )
    assert both.status_code == 200, both.text
    entries = await audit_details(db_session, "system.settings.changed")
    assert [e["section"] for e in entries] == [
        "security.lockout", "security.mfa_policy", "security.admin_networks",
    ]  # fmt: skip
    assert entries[0]["changes"]["security.lockout"] == [
        {"max_failures": 5, "lock_minutes": 15}, {"max_failures": 7, "lock_minutes": 30},
    ]  # fmt: skip
    assert entries[1]["changes"]["security.mfa_policy"][1]["admin"] == "optional"


@pytest.mark.spec("NFR-REL-06")
@pytest.mark.parametrize(
    ("section", "values", "field"),
    [
        ("retention", {"retention.periods": {"audit_months": 5, "app_logs_days": 90,
                       "trash_days": 30, "export_files_hours": 24, "notifications_days": 365,
                       "change_log_days": 7}}, "/values/retention.periods/audit_months"),
        ("security", {"security.password_policy": {"min_length": 100, "max_length": 64,
                      "check_common_passwords": True, "forbid_personal_data": True, "history": 5,
                      "expiry_days": None, "require_uppercase": False, "require_digit": False,
                      "require_special": False, "max_sessions": None}},
         "/values/security.password_policy/min_length"),
        ("digest", {"digest.time": "25:00"}, "/values/digest.time"),
        ("app", {"app.base_url": "http://plain.corp"}, "/values/app.base_url"),
        ("app", {"app.setup": {"completed_at": None, "steps_done": []}}, "/values/app.setup"),
        ("smtp", {"smtp.server": {**SERVER, "from_address": None}},
         "/values/smtp.server/from_address"),
        ("security", {"security.admin_networks": ["not-a-net"]},
         "/values/security.admin_networks/0"),
    ],
)  # fmt: skip
async def test_values_are_checked_by_contract(
    world: World, section: str, values: dict[str, Any], field: str
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    response = await root.put(f"/system/settings/{section}", json={"values": values})
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_FAILED")
    assert field in {e["field"] for e in response.json()["errors"]}


@pytest.mark.spec("SEC-AUTH-07")
@pytest.mark.spec("TC-AUTH-06")
async def test_smtp_secret_encrypted_and_old_server_alerted_first(
    world: World, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    old = {**SERVER, "host": "smtp-old.corp"}
    await set_setting(db_session, "smtp.server", old)
    admin = await make_user(db_session, SystemRole.ADMIN)
    admin.email = f"{admin.login}@corp.ru"
    await db_session.flush()
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)

    saved = await root.put(
        "/system/settings/smtp",
        json={"values": {"smtp.server": SERVER, "smtp.password": "s3cret-pass"}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["smtp.password"] == {"set": True}
    assert "s3cret" not in saved.text
    stored = await _stored(db_session, "smtp.password")
    assert set(stored) == {"enc", "kid"}
    # письмо ИБ — через старый сервер, до записи новых значений
    via_old = [m for m in mails if m[1] == admin.email]
    assert via_old
    assert via_old[0][3]["server"]["host"] == "smtp-old.corp"
    assert via_old[0][4] == notify.OLD_SMTP
    [entry] = await audit_details(db_session, "system.settings.changed")
    assert entry["section"] == "smtp"
    assert entry["changes"]["smtp.password"] in ({"changed": True}, "***")  # ключ маскирует аудит
    assert entry["changes"]["smtp.server"][1]["host"] == "smtp.corp"
    assert "s3cret" not in str(entry)

    # прежний пароль: {"set": true} и тот же открытый текст — изменений нет
    for password in ({"set": True}, "s3cret-pass"):
        same = await root.put("/system/settings/smtp", json={"values": {"smtp.password": password}})
        assert same.status_code == 200
    assert len(await audit_details(db_session, "system.settings.changed")) == 1
    cleared = await root.put("/system/settings/smtp", json={"values": {"smtp.password": None}})
    assert cleared.json()["values"]["smtp.password"] == {"set": False}
    assert await _stored(db_session, "smtp.password") is None


@pytest.mark.spec("SEC-AUTH-05")
async def test_auth_section_waits_for_ad_checks(world: World) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    path = "/system/settings/auth"
    assert (await root.get(path)).json()["values"]["auth.ad.bind_password"] == {"set": False}
    unchanged = await root.put(path, json={"values": {"auth.mode": "local"}})
    assert unchanged.status_code == 200, unchanged.text
    mode = await root.put(path, json={"values": {"auth.mode": "ad"}})
    assert (mode.status_code, mode.json()["code"]) == (422, "VALIDATION_FAILED")
    groups = await root.put(path, json={"values": {"auth.ad.access_groups": ["CN=Est,DC=corp"]}})
    assert (groups.status_code, groups.json()["code"]) == (409, "AD_CHECKS_REQUIRED")
    verification = await root.put(
        path, json={"values": {"auth.ad.verification": {"params_sha256": None,
                    "connection_ok_at": None, "login_ok_at": None}}},
    )  # fmt: skip
    assert verification.status_code == 422


@pytest.mark.spec("FR-NOTIF-02")
async def test_smtp_test_email(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[mail.SmtpConfig] = []

    def fake_send(config: mail.SmtpConfig, to: str, link: str) -> None:
        if not config.configured:
            raise mail.SmtpNotConfiguredError("нет сервера")
        if config.password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        sent.append(config)

    monkeypatch.setattr(mail, "send_test_email", fake_send)
    root = await world.actor(SystemRole.SUPERADMIN)  # без step-up: ничего не записывает
    path, to = "/system/smtp/test", "me@corp.ru"

    nothing = await root.post(path, json={"to": to})
    assert nothing.status_code == 200, nothing.text
    assert (nothing.json()["ok"], nothing.json()["detail"]) == (
        False,
        "Укажите сервер и адрес отправителя",
    )

    form = await root.post(path, json={"to": to, "values": {"smtp.server": SERVER,
                                                            "smtp.password": "pw"}})  # fmt: skip
    assert form.json()["ok"] is True, form.text
    assert sent[-1].password == "pw"
    bad = await root.post(path, json={"to": to, "values": {"smtp.server": SERVER,
                                                           "smtp.password": "wrong"}})  # fmt: skip
    assert (bad.json()["ok"], bad.json()["detail"]) == (False, "Сервер отклонил логин или пароль")

    await step_up(world, root)
    stored = {"smtp.server": SERVER, "smtp.password": "stored-pw"}
    await root.put("/system/settings/smtp", json={"values": stored})
    saved = await root.post(path, json={"to": to})
    assert saved.json()["ok"] is True
    assert sent[-1].password == "stored-pw"
    same = await root.post(path, json={"to": to, "values": {"smtp.server": SERVER}})
    assert sent[-1].password == "stored-pw"
    assert same.json()["ok"] is True
    other = await root.post(path, json={"to": to, "values": {"smtp.server": {**SERVER,
                                                             "host": "evil.example"}}})  # fmt: skip
    assert (other.status_code, other.json()["code"]) == (422, "VALIDATION_FAILED")
    assert await _stored(db_session, "smtp.server") == SERVER  # проверка ничего не пишет
