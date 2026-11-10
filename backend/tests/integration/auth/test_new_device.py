"""AUTH-009: вход с нового устройства (SEC-AUTH-06, Q-12, FR-NOTIF-02)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import devices
from estimator.db.enums import SystemRole
from estimator.db.models.users import KnownDevice, User
from estimator.db.session import run_after_commit
from estimator.notifications import tasks as mail_tasks
from tests.integration.auth.conftest import complete_setup, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUTH-06")]

SERVER = {
    "host": "smtp.corp", "port": 587, "security": "starttls", "username": None,
    "from_address": "robot@corp.ru", "from_name": "Оценка проектов", "timeout_seconds": 10,
}  # fmt: skip
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


async def _user(db: AsyncSession, *roles: SystemRole) -> User:
    user = await make_user(db, *roles)
    user.email = f"{user.login}@corp.ru"
    await db.flush()
    return user


async def _login(api: httpx.AsyncClient, db: AsyncSession, user: User) -> None:
    response = await api.post("/api/v1/auth/login", json={"login": user.login,
                              "password": PASSWORD}, headers={"User-Agent": FIREFOX})  # fmt: skip
    assert response.status_code == 200, response.text
    await db.commit()
    await run_after_commit(db)


async def _letters(mails: list[tuple[Any, ...]], user: User) -> list[dict[str, Any]]:
    return [m[2] for m in mails if m[0] == devices.KIND and m[1] == user.email]


async def _flags(db: AsyncSession, user: User) -> list[bool]:
    rows = await db.execute(text(
        "SELECT details->>'new_device' FROM audit.audit_log "
        "WHERE event_type = 'auth.login.succeeded' AND login = :l ORDER BY id"
    ), {"l": user.login})  # fmt: skip
    return [r[0] == "true" for r in rows]


@pytest.mark.spec("Q-12")
async def test_expert_gets_no_mail_moderator_does(
    api: httpx.AsyncClient, db_session: AsyncSession, mails: list[tuple[Any, ...]]
) -> None:
    await complete_setup(db_session)
    await set_setting(db_session, "smtp.server", SERVER)
    expert = await _user(db_session)
    moderator = await _user(db_session, SystemRole.MODERATOR)

    await _login(api, db_session, expert)
    assert await _letters(mails, expert) == [], "эксперт денег не видит — письма нет"
    assert await _flags(db_session, expert) == [True]

    await _login(api, db_session, moderator)
    [letter] = await _letters(mails, moderator)
    assert letter["browser"] == "Firefox"
    assert letter["subnet"].endswith(".0/24")
    assert letter["link"].endswith("/profile")
    assert set(letter) == {"browser", "subnet", "time", "link"}

    await _login(api, db_session, moderator)
    assert len(await _letters(mails, moderator)) == 1, "знакомое устройство — без письма"
    long_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=devices.FRESH_DAYS + 1)
    await db_session.execute(
        update(KnownDevice).where(KnownDevice.user_id == moderator.id)
        .values(last_seen_at=long_ago)
    )  # fmt: skip
    await _login(api, db_session, moderator)
    assert len(await _letters(mails, moderator)) == 2, "90 дней без входа — снова новое"
    assert await _flags(db_session, moderator) == [True, False, True]
    [device] = (await db_session.scalars(
        select(KnownDevice).where(KnownDevice.user_id == moderator.id)
    )).all()  # fmt: skip
    assert device.ua_family == "Firefox"
    assert device.last_seen_at > long_ago


def test_browser_family_and_subnet() -> None:
    chrome = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")  # fmt: skip
    assert devices.browser_family(chrome) == "Chrome"
    assert devices.browser_family(chrome + " Edg/130.0.0.0") == "Edge"
    assert devices.browser_family(chrome + " YaBrowser/24.10.0.0") == "Яндекс.Браузер"
    assert devices.browser_family(chrome + " OPR/114.0.0.0") == "Opera"
    assert devices.browser_family(FIREFOX) == "Firefox"
    assert devices.browser_family(
        "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605"
        ".1.15"
    ) == "Safari"  # fmt: skip
    assert devices.browser_family(None) == devices.OTHER
    assert str(devices.subnet_of("10.1.2.3")) == "10.1.2.0/24"
    assert str(devices.subnet_of("::ffff:10.1.2.3")) == "10.1.2.0/24"
    assert str(devices.subnet_of("2001:db8:1:2::5")) == "2001:db8:1:2::/64"
