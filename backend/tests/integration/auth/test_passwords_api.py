"""AUTH-008: активация, «Забыли пароль», сброс и смена пароля (FR-AUTH-LOC-01…04)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.passwords import issue_activation
from estimator.auth.sessions import COOKIE_NAME
from estimator.auth.tokens import issue
from estimator.db.enums import AuthTokenKind, UserStatus
from estimator.db.models.users import AuthToken, PasswordHistory
from tests.integration.auth.conftest import complete_setup, csrf_headers
from tests.integration.auth.helpers import PASSWORD, make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-LOC-02")]

NEW = "Grey violet ocean 2026"  # nosec B105 — тестовый пароль


def _token(link: str) -> str:
    return link.rpartition("token=")[2]


async def _audit(db: AsyncSession, event: str, user_id: Any) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = :e AND user_id = :u ORDER BY id"
        ),
        {"e": event, "u": user_id},
    )
    return [r[0] for r in rows]


@pytest.mark.spec("FR-AUTH-LOC-01")
async def test_activation_link(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session, status=UserStatus.PENDING_PASSWORD, password_hash_value=None)
    issued = await issue_activation(db_session, user, created_by=None)
    assert not issued.emailed, "без SMTP ссылка показывается администратору"
    assert issued.link.startswith("https://localhost/activate?token=")
    token = _token(issued.link)
    row = await db_session.scalar(select(AuthToken).where(AuthToken.user_id == user.id))
    assert row is not None
    assert row.token_hash != token.encode(), "в БД только хэш"
    assert row.expires_at - row.created_at == timedelta(hours=72)

    weak = await api.post(
        "/api/v1/auth/activate", json={"token": token, "password": "password1234"}
    )
    assert weak.status_code == 422
    assert (weak.json()["code"], weak.json()["violations"]) == ("PASSWORD_POLICY_VIOLATION", ["common"])
    ok = await api.post("/api/v1/auth/activate", json={"token": token, "password": NEW})
    assert ok.status_code == 204
    await db_session.refresh(user)
    assert user.status is UserStatus.ACTIVE
    login = await api.post("/api/v1/auth/login", json={"login": user.login, "password": NEW})
    assert login.json()["step"] == "done"
    used = await api.post("/api/v1/auth/activate", json={"token": token, "password": NEW + "x"})
    assert used.status_code == 410
    assert used.json()["code"] == "TOKEN_INVALID"
    assert await _audit(db_session, "auth.password.set", user.id) == [{"via": "activation"}]


async def test_new_link_revokes_old_and_expiry(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await make_user(db_session, status=UserStatus.PENDING_PASSWORD, password_hash_value=None)
    old = await issue(db_session, user.id, AuthTokenKind.ACTIVATION)
    new = await issue(db_session, user.id, AuthTokenKind.ACTIVATION)
    response = await api.post("/api/v1/auth/activate", json={"token": old, "password": NEW})
    assert response.status_code == 410
    await db_session.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    expired = await api.post("/api/v1/auth/activate", json={"token": new, "password": NEW})
    assert expired.status_code == 410


@pytest.mark.spec("FR-AUTH-LOC-03")
async def test_forgot_is_uniform_and_reset_ends_sessions(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session)
    a = await api.post("/api/v1/auth/password/forgot", json={"login_or_email": user.login})
    b = await api.post(
        "/api/v1/auth/password/forgot", json={"login_or_email": "nobody@example.org"}
    )
    assert a.status_code == b.status_code == 204
    assert a.content == b.content == b""
    assert await _audit(db_session, "auth.password.reset_requested", user.id) == [
        {"email_sent": False, "actor": "anonymous"}
    ]

    await api.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
    assert api.cookies.get(COOKIE_NAME)
    token = await issue(db_session, user.id, AuthTokenKind.PASSWORD_RESET)
    row = await db_session.scalar(select(AuthToken).where(AuthToken.user_id == user.id))
    assert row is not None
    assert row.expires_at - row.created_at == timedelta(minutes=60)
    reset = await api.post("/api/v1/auth/password/reset", json={"token": token, "password": NEW})
    assert reset.status_code == 204
    me = await api.post("/api/v1/auth/logout", headers=csrf_headers(api))
    assert me.status_code == 401, "после сброса все сессии завершены"
    assert await _audit(db_session, "auth.sessions.terminated", user.id) == [
        {"count": 1, "reason": "password_reset"}
    ]


@pytest.mark.spec("FR-AUTH-LOC-04")
async def test_change_password_keeps_current_session(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await complete_setup(db_session)
    user = await make_user(db_session)
    other = httpx.AsyncClient(transport=api._transport, base_url="https://test")
    async with other:
        await other.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
        await api.post("/api/v1/auth/login", json={"login": user.login, "password": PASSWORD})
        wrong = await api.post(
            "/api/v1/me/password",
            json={"current_password": "not mine", "new_password": NEW},
            headers=csrf_headers(api),
        )
        assert wrong.status_code == 422
        assert wrong.json()["code"] == "CURRENT_PASSWORD_INVALID"
        personal = await api.post(
            "/api/v1/me/password",
            json={"current_password": PASSWORD, "new_password": f"my {user.login} secret"},
            headers=csrf_headers(api),
        )
        assert personal.json()["violations"] == ["matches_personal"]
        ok = await api.post(
            "/api/v1/me/password",
            json={"current_password": PASSWORD, "new_password": NEW},
            headers=csrf_headers(api),
        )
        assert ok.status_code == 204
        assert (
            await other.post("/api/v1/auth/logout", headers=csrf_headers(other))
        ).status_code == 401
        assert (await api.post("/api/v1/auth/logout", headers=csrf_headers(api))).status_code == 204
    history = await db_session.scalar(
        select(func.count()).select_from(PasswordHistory).where(PasswordHistory.user_id == user.id)
    )
    assert history == 1
    back = await api.post("/api/v1/auth/login", json={"login": user.login, "password": NEW})
    assert back.json()["step"] == "done"
    newer = await api.post(
        "/api/v1/me/password",
        json={"current_password": NEW, "new_password": NEW + " again"},
        headers=csrf_headers(api),
    )
    assert newer.status_code == 204
    reuse = await api.post(
        "/api/v1/me/password",
        json={"current_password": NEW + " again", "new_password": NEW},
        headers=csrf_headers(api),
    )
    assert reuse.json()["violations"] == ["reused"], "прежний пароль из истории"
