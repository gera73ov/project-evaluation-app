"""SEC-014: анонимизация заблокированного пользователя (SEC-PD-03, Q-34; CR-010 — список).

Только суперадминистратор со step-up и только заблокированная учётка. После анонимизации ФИО —
«Удалённый пользователь #N», логин и почта случайные, сессии, 2FA, роли и связь с AD сняты; строка
пользователя и журнал аудита остаются.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from ipaddress import ip_address, ip_network
from typing import Any

import httpx
import pyotp
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import AuthTokenKind, SystemRole, UserSource, UserStatus
from estimator.db.models.users import (
    AuthToken,
    BackupCode,
    KnownDevice,
    PasswordHistory,
    User,
    UserRole,
    UserSession,
)
from estimator.security.pd import anonymize as pd
from tests.integration.auth.conftest import complete_setup, csrf_headers, set_setting
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-PD-03")]

NOW = dt.datetime.now(dt.UTC)


async def _superadmin_session(
    api: httpx.AsyncClient, db: AsyncSession, redis: Redis
) -> tuple[User, str]:
    """Вошедший суперадминистратор с подключённым TOTP; возвращает его и секрет."""
    await complete_setup(db)
    await set_setting(db, "security.admin_networks", [])
    sa = await make_user(db, SystemRole.SUPERADMIN)
    login = await api.post("/api/v1/auth/login", json={"login": sa.login, "password": PASSWORD})
    assert login.status_code == 200, login.text
    started = await api.post("/api/v1/auth/totp/enroll", headers=csrf_headers(api))
    secret = started.json()["secret"]
    confirmed = await api.post(
        "/api/v1/auth/totp/enroll/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(api),
    )
    assert confirmed.status_code == 200, confirmed.text
    await redis.delete(f"totp:last:{sa.id}")
    return sa, secret


async def _step_up(api: httpx.AsyncClient, secret: str) -> None:
    response = await api.post(
        "/api/v1/auth/step-up",
        json={"code": pyotp.TOTP(secret).at(time.time() + 30), "password": PASSWORD},
        headers=csrf_headers(api),
    )
    assert response.status_code == 200, response.text


async def _blocked(db: AsyncSession, *roles: SystemRole, **kw: Any) -> User:
    user = await make_user(db, *roles, status=UserStatus.BLOCKED, **kw)
    user.email = f"{user.login}@example.com"
    user.blocked_at = NOW
    await db.flush()
    return user


async def _personal_rows(db: AsyncSession, user_id: uuid.UUID) -> None:
    db.add_all([
        BackupCode(user_id=user_id, code_hash="x"),
        PasswordHistory(user_id=user_id, password_hash="x"),
        KnownDevice(user_id=user_id, ua_family="Firefox", subnet=ip_network("10.1.2.0/24"),
                    last_seen_at=NOW),
        AuthToken(user_id=user_id, kind=AuthTokenKind.PASSWORD_RESET, token_hash=uuid.uuid4().bytes,
                  expires_at=NOW + dt.timedelta(hours=1)),
        UserSession(id_hash=uuid.uuid4().bytes, user_id=user_id, last_seen_at=NOW,
                    expires_at=NOW + dt.timedelta(hours=1), ip=ip_address("10.1.2.3")),
    ])  # fmt: skip
    await db.flush()


async def _count(db: AsyncSession, model: Any, user_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(
        model.user_id == user_id)) or 0)  # fmt: skip


@pytest.mark.spec("Q-34")
async def test_superadmin_anonymizes_blocked_user(
    api: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis
) -> None:
    sa, secret = await _superadmin_session(api, db_session, redis_client)
    guid = uuid.uuid4()
    target = await _blocked(db_session, SystemRole.MODERATOR, source=UserSource.AD)
    target.ad_object_guid = guid
    target.totp_enabled, target.totp_secret_enc = True, b"enc"
    await db_session.flush()
    await _personal_rows(db_session, target.id)
    active = await make_user(db_session)

    listed = await api.get("/api/v1/system/users", params={"q": target.login})
    assert listed.status_code == 200, listed.text  # просмотр списка — без step-up
    assert [i["id"] for i in listed.json()["items"]] == [str(target.id)]
    assert listed.json()["items"][0]["roles"] == ["moderator"]
    assert "email" not in listed.json()["items"][0]
    await _blocked(db_session)
    first = (await api.get("/api/v1/system/users", params={"limit": 1})).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    second = await api.get(
        "/api/v1/system/users", params={"limit": 1, "cursor": first["next_cursor"]}
    )
    assert second.status_code == 200
    assert second.json()["items"] != first["items"]
    forged = await api.get("/api/v1/system/users", params={"cursor": "abc"})
    assert (forged.status_code, forged.json()["code"]) == (400, "CURSOR_INVALID")

    url = f"/api/v1/system/users/{target.id}/anonymize"
    denied = await api.post(url, headers=csrf_headers(api))
    assert (denied.status_code, denied.json()["code"]) == (403, "STEP_UP_REQUIRED")

    await _step_up(api, secret)
    not_blocked = await api.post(
        f"/api/v1/system/users/{active.id}/anonymize", headers=csrf_headers(api)
    )
    assert (not_blocked.status_code, not_blocked.json()["code"]) == (409, "USER_NOT_BLOCKED")
    missing = await api.post(
        f"/api/v1/system/users/{uuid.uuid4()}/anonymize", headers=csrf_headers(api)
    )
    assert missing.status_code == 404

    old_login = target.login
    done = await api.post(url, headers=csrf_headers(api))
    assert done.status_code == 204, done.text

    await db_session.refresh(target)
    assert target.status is UserStatus.ANONYMIZED
    assert target.block_reason is None
    assert target.full_name == f"Удалённый пользователь #{target.anonymized_no}"
    assert target.login != old_login
    assert target.login.startswith("deleted-")
    assert target.email
    assert target.email.endswith("@anonymized.invalid")
    assert target.ad_object_guid is None
    assert (target.totp_enabled, target.totp_secret_enc) == (False, None)
    for model in (BackupCode, PasswordHistory, KnownDevice, AuthToken, UserRole, UserSession):
        assert await _count(db_session, model, target.id) == 0, model.__name__

    rows = await db_session.execute(
        text("SELECT user_id, details FROM audit.audit_log WHERE event_type = 'users.anonymized'"
             " AND object_id = :o"), {"o": str(target.id)},
    )  # fmt: skip
    assert [(r[0], r[1]) for r in rows] == [(sa.id, {"anonymous_no": target.anonymized_no})]

    again = await api.post(url, headers=csrf_headers(api))
    assert (again.status_code, again.json()["code"]) == (409, "USER_NOT_BLOCKED")
    gone = await api.get("/api/v1/system/users", params={"q": old_login})
    assert gone.json()["items"] == []
    anonymized = await api.get(
        "/api/v1/system/users", params={"status": "anonymized", "q": target.full_name}
    )
    assert [i["id"] for i in anonymized.json()["items"]] == [str(target.id)]

    # Связь с AD снята: новый вход того же человека создаёт новую учётку с тем же GUID
    fresh = await make_user(db_session, source=UserSource.AD)
    fresh.ad_object_guid = guid
    await db_session.flush()
    assert fresh.id != target.id


@pytest.mark.spec("SEC-AUTH-05")
async def test_only_superadmin_sees_the_list(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    await set_setting(db_session, "security.mfa_policy", {"user": "optional"})
    user = await make_user(db_session)
    login = await api.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert (await api.get("/api/v1/system/users")).status_code in (403, 404)
    target = await _blocked(db_session)
    response = await api.post(
        f"/api/v1/system/users/{target.id}/anonymize", headers=csrf_headers(api)
    )
    assert response.status_code in (403, 404)


async def test_list_pages_and_filters(db_session: AsyncSession) -> None:
    tag = uuid.uuid4().hex[:8]
    users = []
    for i in range(5):
        user = await _blocked(db_session)
        user.full_name = f"Список {tag} {i}"
        user.blocked_at = NOW - dt.timedelta(minutes=i // 2)  # пары с одинаковой датой
        users.append(user)
    await db_session.flush()
    expected = sorted(users, key=lambda u: (-u.blocked_at.timestamp(), u.id))  # type: ignore[union-attr]

    seen: list[uuid.UUID] = []
    after = None
    while True:
        rows = await pd.list_users(db_session, pd.ListFilter(q=tag), after=after, limit=2)
        seen += [r["id"] for r in rows[:2]]
        if len(rows) <= 2:
            break
        after = {"k": rows[1]["_k"], "id": str(rows[1]["id"])}
    assert seen == [u.id for u in expected]

    none = await pd.list_users(
        db_session, pd.ListFilter(status=UserStatus.ANONYMIZED, q=tag), after=None, limit=10
    )
    assert none == []
    escaped = await pd.list_users(db_session, pd.ListFilter(q="%"), after=None, limit=10)
    assert all("%" in r["login"] or "%" in r["full_name"] for r in escaped)


BAD_POSITIONS = [
    {"k": "вчера", "id": "x"},
    {"id": str(uuid.uuid4())},
    {"k": "2026-01-01T00:00:00", "id": str(uuid.uuid4())},  # без часового пояса
]


@pytest.mark.parametrize("after", BAD_POSITIONS)
async def test_bad_cursor_position(db_session: AsyncSession, after: dict[str, Any]) -> None:
    from estimator.api.common.errors import ApiError

    with pytest.raises(ApiError) as caught:
        await pd.list_users(db_session, pd.ListFilter(), after=after, limit=1)
    assert caught.value.code == "CURSOR_INVALID"
