"""AUTH-003: current_principal — актуальные статус и роли на каждом запросе."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import CurrentPrincipal, get_session_service
from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import COOKIE_NAME, RevokeReason, SessionService, id_hash
from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.db.session import db_session as db_session_dependency
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import as_app

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SESS-05")]


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(redis_client: Redis, clock: Clock) -> SessionService:
    return SessionService(redis_client, clock)


@pytest.fixture
async def client(
    db_session: AsyncSession, service: SessionService
) -> AsyncIterator[httpx.AsyncClient]:
    await as_app(db_session)
    app = FastAPI()

    @app.get("/me")
    async def me(principal: CurrentPrincipal) -> dict[str, object]:
        return {
            "login": principal.login,
            "roles": sorted(principal.roles),
            "mfa": principal.mfa_passed,
            "enrollment": principal.enrollment_required,
        }

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[get_session_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


async def _get(
    client: httpx.AsyncClient, sid: str | None, headers: dict[str, str] | None = None
) -> httpx.Response:
    client.cookies.clear()
    if sid is not None:
        client.cookies.set(COOKIE_NAME, sid)
    return await client.get("/me", headers=headers)


async def _login(db: AsyncSession, service: SessionService, *roles: SystemRole) -> tuple[User, str]:
    user = await make_user(db, *roles)
    sid, _ = await service.create(db, user.id, roles, SessionPolicy(), ip="10.0.0.1")
    return user, sid


async def test_no_cookie_or_unknown_is_401(client: httpx.AsyncClient) -> None:
    for sid in (None, "forged"):
        response = await _get(client, sid)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_roles_are_read_on_every_request(
    client: httpx.AsyncClient, db_session: AsyncSession, service: SessionService
) -> None:
    user, sid = await _login(db_session, service, SystemRole.MODERATOR)
    response = await _get(client, sid)
    assert response.status_code == 200
    assert response.json() == {
        "login": user.login, "roles": ["moderator"], "mfa": False, "enrollment": False,
    }  # fmt: skip
    db_session.add(UserRole(user_id=user.id, role=SystemRole.PRESALE, source=RoleSource.MANUAL))
    await db_session.flush()
    response = await _get(client, sid)
    assert response.json()["roles"] == ["moderator", "presale"]


async def test_blocked_user_gets_401_on_next_request(
    client: httpx.AsyncClient, db_session: AsyncSession, service: SessionService
) -> None:
    user, sid = await _login(db_session, service)
    assert (await _get(client, sid)).status_code == 200
    await db_session.execute(
        update(User)
        .where(User.id == user.id)
        .values(status=UserStatus.BLOCKED, block_reason=UserBlockReason.MANUAL)
    )
    assert (await _get(client, sid)).status_code == 401
    assert (await service.load(sid)).record is None, "сессия заблокированного закрыта"


@pytest.mark.spec("FR-SESS-01")
async def test_logout_then_old_cookie_is_401(
    client: httpx.AsyncClient, db_session: AsyncSession, service: SessionService
) -> None:
    user, sid = await _login(db_session, service)
    await service.end(db_session, sid, user.id, RevokeReason.LOGOUT)
    assert (await _get(client, sid)).status_code == 401


@pytest.mark.spec("FR-SESS-02")
async def test_background_requests_do_not_extend(
    client: httpx.AsyncClient, db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    _user, sid = await _login(db_session, service)
    statuses = []
    for _ in range(3):
        clock.now += 25 * 60
        response = await _get(client, sid, headers={"X-Background": "1"})
        statuses.append(response.status_code)
    # 75 минут без пользовательских запросов > 60 минут бездействия
    assert statuses == [200, 200, 401]
    expired = (
        await db_session.execute(
            text(
                "SELECT details->>'reason', session_hash FROM audit.audit_log "
                "WHERE event_type = 'auth.session.expired' ORDER BY id DESC LIMIT 1"
            )
        )
    ).one()
    assert expired[0] == "idle"
    assert bytes(expired[1]) == id_hash(sid)


@pytest.mark.spec("FR-SESS-02")
async def test_user_requests_extend(
    client: httpx.AsyncClient, db_session: AsyncSession, service: SessionService, clock: Clock
) -> None:
    _user, sid = await _login(db_session, service)
    for _ in range(3):
        clock.now += 25 * 60
        assert (await _get(client, sid)).status_code == 200
