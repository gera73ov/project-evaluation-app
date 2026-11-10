"""AUTH-018: переход «Приложение → AD» (FR-AUTH-SW-01, C-13, G-10, G-11) — на имитации AD."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import switch_mode
from estimator.auth.policy import load_auth_mode
from estimator.auth.providers import ldap
from estimator.db.enums import SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import PasswordHistory, User, UserSession
from tests.integration.adm.helpers import step_up
from tests.integration.auth.helpers import make_user
from tests.integration.core.conftest import World, deliver_events
from tests.support import fake_ad as support
from tests.support.fake_ad import FakeDirectory

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-SW-01")]

PATH = "/system/auth/switch-mode"


@pytest.fixture
async def directory(
    world: World, db_session: AsyncSession, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeDirectory]:
    tag = f"test:{id(db_session)}"
    monkeypatch.setattr(switch_mode, "DECISIONS_KEY", f"{tag}:{switch_mode.DECISIONS_KEY}")
    monkeypatch.setattr(switch_mode, "LAST_KEY", f"{tag}:{switch_mode.LAST_KEY}")
    fake = FakeDirectory()
    ldap.set_directory_factory(lambda _config: fake)
    await support.configure(db_session, mode="local")
    yield fake
    ldap.set_directory_factory(None)
    await redis_client.delete(switch_mode.DECISIONS_KEY, switch_mode.LAST_KEY)


def _logins(items: list[dict[str, Any]]) -> list[str]:
    return sorted(i["login"] for i in items)


async def _local(db: AsyncSession, login: str, full_name: str) -> User:
    user = await make_user(db)
    user.login, user.full_name = login, full_name
    await db.flush()
    return user


@pytest.mark.spec("C-13")
async def test_switch_report_resolve_apply(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    ivanov = await _local(db_session, "ivanov", "Иванов Иван")
    petrov = await _local(db_session, "petrov", "Петров Пётр")
    dup = await _local(db_session, "dup", "Дубль Один")
    ghost = await _local(db_session, "ghost", "Призрак")
    db_session.add(PasswordHistory(user_id=ivanov.id, password_hash=ivanov.password_hash or "x"))
    await db_session.flush()
    directory.add("IVANOV", full_name="Иванов  Иван")
    other = directory.add("petrov", full_name="Петров Павел")
    directory.add("dup", full_name="Дубль Один")
    directory.add("Dup", full_name="Дубль Два")
    colleague = await world.session_for(ivanov.id)

    dry = await root.post(PATH, json={"mode": "ad", "dry_run": True})
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert _logins(body["matched"]) == ["ivanov"], "по логину без регистра, ФИО совпало"
    assert _logins(body["ambiguous"]) == ["dup", "petrov"]
    assert "ghost" in _logins(body["not_found"])
    assert body["applied"] is False
    assert await load_auth_mode(db_session) == "local"

    early = await root.post(PATH, json={"mode": "ad", "dry_run": False})
    assert (early.status_code, early.json()["code"]) == (409, "MODE_SWITCH_UNRESOLVED")
    assert early.json()["unresolved"] == 2

    resolved = await root.post(f"{PATH}/resolve", json={"decisions": [
        {"user_id": str(petrov.id), "object_guid": str(other.entry.object_guid)},
        {"user_id": str(dup.id), "object_guid": None},
    ]})  # fmt: skip
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["ambiguous"] == []
    assert {"ivanov", "petrov"} <= set(_logins(resolved.json()["matched"]))

    applied = await root.post(PATH, json={"mode": "ad", "dry_run": False})
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    assert await load_auth_mode(db_session) == "ad"
    for user in (ivanov, petrov):
        await db_session.refresh(user)
        assert (user.source, user.password_hash) == (UserSource.AD, None)
        assert user.ad_object_guid is not None
    assert await db_session.scalar(
        select(PasswordHistory).where(PasswordHistory.user_id == ivanov.id)
    ) is None, "история паролей удалена"  # fmt: skip
    for user in (dup, ghost):
        await db_session.refresh(user)
        assert (user.status, user.block_reason) == (UserStatus.BLOCKED,
                                                    UserBlockReason.NOT_MATCHED)  # fmt: skip
    alive = select(UserSession.user_id).where(UserSession.revoked_at.is_(None))
    open_ = (await db_session.scalars(alive.execution_options(populate_existing=True))).all()
    assert root.id in open_, "сессия суперадминистратора остаётся"
    assert colleague.id not in open_, "остальные сессии завершены"
    rows = await db_session.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = 'system.auth_mode.switched' "
        "ORDER BY id"))  # fmt: skip
    details = [r[0] for r in rows]
    assert [d["dry_run"] for d in details] == [True, False]
    assert (details[-1]["ambiguous_confirmed"], details[-1]["ambiguous_rejected"]) == (1, 1)

    await deliver_events(db_session)
    last = await root.get(f"{PATH}/last")
    assert last.status_code == 200, last.text
    assert last.json()["resolved"] == 2
    assert last.json()["by"]["id"] == str(root.id)


async def test_switch_not_allowed(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    assert (await root.get(f"{PATH}/last")).json() is None
    back = await root.post(PATH, json={"mode": "local", "dry_run": True})
    assert (back.status_code, back.json()["code"]) == (409, "MODE_SWITCH_NOT_ALLOWED")
    await support.configure(db_session, mode="ad")
    again = await root.post(PATH, json={"mode": "ad", "dry_run": True})
    assert (again.status_code, again.json()["code"]) == (409, "MODE_SWITCH_NOT_ALLOWED")


async def test_switch_requires_checked_settings(
    world: World, db_session: AsyncSession, directory: FakeDirectory
) -> None:
    from tests.integration.auth.conftest import set_setting

    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    empty = {"params_sha256": None, "connection_ok_at": None, "login_ok_at": None}
    await set_setting(db_session, "auth.ad.verification", empty)
    response = await root.post(PATH, json={"mode": "ad", "dry_run": True})
    assert (response.status_code, response.json()["code"]) == (409, "AD_CHECKS_REQUIRED")
