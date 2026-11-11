"""QA-012 · отзыв доступа и синхронизация с настоящим AD (TC-AUTH-02, G-26; FR-AUTH-AD-08, Q-18,
AUTH-016) на Samba AD DC.

Пользователь входит через API (настоящая сессия), затем его меняют в Samba, и отрабатывает та же
проверка, что запускает beat каждые 15 минут (``ad_sync.run(..., SESSIONS)``; расписание —
``test_ad_sync.test_schedule_registered``). Запуск: ``make up-test && make test-ad``.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import ad_sync
from estimator.db.enums import UserBlockReason, UserStatus
from estimator.db.models.users import User
from tests.integration.core.conftest import World
from tests.support import samba as ad
from tests.support.samba import AdUser, Samba

pytestmark = [pytest.mark.integration, pytest.mark.samba, pytest.mark.tc("TC-AUTH-02"),
              pytest.mark.spec("FR-AUTH-AD-08")]  # fmt: skip


@pytest.fixture(autouse=True)
def state_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свой ключ состояния у каждого теста: Redis общий для тестов и стенда."""
    monkeypatch.setattr(ad_sync, "STATE_KEY", f"test:{uuid.uuid4().hex[:8]}:{ad_sync.STATE_KEY}")


@pytest.fixture
async def on_samba(world: World, db_session: AsyncSession, samba: Samba) -> Samba:
    await samba.configure(db_session)
    return samba


async def _signed_in(world: World, person: AdUser) -> httpx.AsyncClient:
    """Вход через AD; клиент с cookie сессии."""
    world.api.cookies.clear()
    response = await world.api.post(
        "/api/v1/auth/login", json={"login": person.login, "password": person.password}
    )
    assert response.status_code == 200, response.text
    return world.api


async def _me(world: World, cookies: httpx.Cookies) -> int:
    world.api.cookies = cookies
    return (await world.api.get("/api/v1/me")).status_code


async def _state(db: AsyncSession, person: AdUser) -> tuple[UserStatus, UserBlockReason | None]:
    user = await db.scalar(select(User).where(User.ad_object_guid == person.object_guid)
                           .execution_options(populate_existing=True))  # fmt: skip
    assert user is not None
    return user.status, user.block_reason


async def test_disabled_in_ad_ends_session(
    world: World, db_session: AsyncSession, redis_client: Redis, on_samba: Samba
) -> None:
    person = on_samba.add_user("dis")
    cookies = httpx.Cookies((await _signed_in(world, person)).cookies)
    assert await _me(world, cookies) == 200

    on_samba.set_disabled(person)
    summary = await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert (summary.checked, summary.blocked, summary.skipped_ad_unavailable) == (1, 1, False)
    assert await _state(db_session, person) == (UserStatus.BLOCKED, UserBlockReason.AD_DISABLED)
    assert await _me(world, cookies) == 401, "сессия завершена проверкой (≤ 15 минут)"

    on_samba.set_disabled(person, False)
    again = await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    assert again.unblocked == 1
    assert await _state(db_session, person) == (UserStatus.ACTIVE, None), "причина ушла — снято"


@pytest.mark.gherkin("G-26")
async def test_removed_from_access_group(
    world: World, db_session: AsyncSession, redis_client: Redis, on_samba: Samba
) -> None:
    team = on_samba.add_group("acc", member_of=[ad.ACCESS])
    person = on_samba.add_user("grp", groups=[team])  # доступ через вложенную группу
    cookies = httpx.Cookies((await _signed_in(world, person)).cookies)

    on_samba.remove_member(team, person.dn)
    await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert await _state(db_session, person) == (UserStatus.BLOCKED, UserBlockReason.AD_GROUP)
    assert await _me(world, cookies) == 401


async def test_deleted_in_ad(
    world: World, db_session: AsyncSession, redis_client: Redis, on_samba: Samba
) -> None:
    person = on_samba.add_user("gone")
    await _signed_in(world, person)
    on_samba.delete(person)
    await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert await _state(db_session, person) == (UserStatus.BLOCKED, UserBlockReason.AD_MISSING)


async def test_manual_block_survives_sync(
    world: World, db_session: AsyncSession, redis_client: Redis, on_samba: Samba
) -> None:
    person = on_samba.add_user("man")
    await _signed_in(world, person)
    user = await db_session.scalar(select(User).where(User.ad_object_guid == person.object_guid))
    assert user is not None
    user.status, user.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db_session.flush()

    for kind in (ad_sync.SESSIONS, ad_sync.DAILY):
        await ad_sync.run(db_session, redis_client, kind)
        assert await _state(db_session, person) == (UserStatus.BLOCKED, UserBlockReason.MANUAL)
    world.api.cookies.clear()
    refused = await world.api.post(
        "/api/v1/auth/login", json={"login": person.login, "password": person.password}
    )
    assert refused.status_code == 401, "в AD всё в порядке, но ручную блокировку снимает человек"


async def test_daily_refreshes_name_and_login(
    world: World, db_session: AsyncSession, redis_client: Redis, on_samba: Samba
) -> None:
    person = on_samba.add_user("day", full_name="Суточная Анна")
    await _signed_in(world, person)
    new_login = on_samba.name("dnew")
    on_samba.rename(person, new_login, full_name="Суточная Анна Петровна")
    await ad_sync.run(db_session, redis_client, ad_sync.DAILY)
    user = await db_session.scalar(select(User).where(User.ad_object_guid == person.object_guid)
                                   .execution_options(populate_existing=True))  # fmt: skip
    assert user is not None
    assert (user.login, user.full_name) == (new_login, "Суточная Анна Петровна")


async def test_controller_down_changes_nothing(
    world: World, db_session: AsyncSession, redis_client: Redis, samba: Samba
) -> None:
    await samba.configure(db_session)
    person = samba.add_user("down")
    cookies = httpx.Cookies((await _signed_in(world, person)).cookies)
    samba.set_disabled(person)
    await samba.configure(db_session, controllers=[{"host": samba.env.host, "port": 1}])
    summary = await ad_sync.run(db_session, redis_client, ad_sync.SESSIONS)
    assert summary.skipped_ad_unavailable
    assert await _state(db_session, person) == (UserStatus.ACTIVE, None)
    assert await _me(world, cookies) == 200, "AD недоступен — сессии не трогаем"
