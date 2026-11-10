"""AUTH-019: переход «AD → Приложение» консольной командой (FR-AUTH-SW-01, 18.2)."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth import passwords
from estimator.auth.policy import SessionPolicy, load_auth_mode, read_settings
from estimator.auth.providers import ldap
from estimator.auth.sessions import SessionService
from estimator.auth.switch_mode import to_local as switch
from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import User, UserRole, UserSession
from estimator.notifications import tasks
from tests.integration.auth.helpers import make_user
from tests.integration.core.conftest import deliver_events
from tests.support import fake_ad as support

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-AUTH-SW-01"),
              pytest.mark.usefixtures("encryption_key")]  # fmt: skip
NEW_PASSWORD = "new horse battery staple 2026"  # nosec B105 — тестовый пароль


async def _ad_user(db: AsyncSession, login: str, *, email: str | None = None,
                   status: UserStatus = UserStatus.ACTIVE) -> User:  # fmt: skip
    user = User(
        login=login,
        full_name=f"Сотрудник {login}",
        email=email,
        source=UserSource.AD,
        ad_object_guid=uuid.uuid4(),
        status=status,
        block_reason=UserBlockReason.AD_MISSING if status is UserStatus.BLOCKED else None,
    )
    db.add(user)
    await db.flush()
    return user


async def _session(db: AsyncSession, redis: Redis, user: User) -> None:
    await SessionService(redis).create(db, user.id, [], SessionPolicy(), ip="10.1.2.3",
                                       mfa_passed=True)  # fmt: skip


async def _alive(db: AsyncSession) -> set[uuid.UUID]:
    rows = await db.scalars(select(UserSession.user_id).where(UserSession.revoked_at.is_(None))
                            .execution_options(populate_existing=True))  # fmt: skip
    return set(rows.all())


async def _switched(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT details FROM audit.audit_log WHERE event_type = 'system.auth_mode.switched' "
        "ORDER BY id"))  # fmt: skip
    return [{k: v for k, v in r[0].items() if k != "actor"} for r in rows]


async def test_ad_to_local_with_handouts(db_session: AsyncSession, redis_client: Redis) -> None:
    db = db_session
    await support.configure(db, mapping=[(support.MODERATORS, "moderator")])
    lead = await _ad_user(db, "lead", email="lead@corp.local")
    gone = await _ad_user(db, "gone", status=UserStatus.BLOCKED)
    db.add(UserRole(user_id=lead.id, role=SystemRole.MODERATOR, source=RoleSource.AD_GROUP))
    root = await make_user(db, SystemRole.SUPERADMIN)
    await _session(db, redis_client, lead)
    await _session(db, redis_client, root)

    dry = await switch.to_local(db, redis_client, os_user="ops", dry_run=True)
    assert (dry.converted, dry.blocked, dry.handouts) == (2, ["gone"], [])
    assert await load_auth_mode(db) == "ad"

    result = await switch.to_local(db, redis_client, os_user="ops")
    assert result.smtp is False, "SMTP не настроен — ссылки в CSV"
    assert [h.login for h in result.handouts] == ["lead"]
    assert result.roles_made_manual == 1
    assert await load_auth_mode(db) == "local"
    mapping = (await read_settings(db, ldap.ROLE_MAPPING))[ldap.ROLE_MAPPING]
    assert mapping["enabled"] is False
    role = await db.scalar(select(UserRole).where(UserRole.user_id == lead.id))
    assert role is not None
    assert role.source is RoleSource.MANUAL, "роль из группы — ручная"
    for user in (lead, gone):
        await db.refresh(user)
        assert (user.source, user.ad_object_guid, user.password_hash) == (
            UserSource.LOCAL, None, None)  # fmt: skip
    assert lead.status is UserStatus.PENDING_PASSWORD
    assert (gone.status, gone.block_reason) == (UserStatus.BLOCKED, UserBlockReason.AD_MISSING)
    assert await _alive(db) == {root.id}, "сессии суперадминистраторов остаются"
    assert [d["dry_run"] for d in await _switched(db)] == [True, False]
    last = (await _switched(db))[-1]
    assert {k: last[k] for k in ("from", "to", "via", "matched", "not_found_blocked")} == {
        "from": "ad",
        "to": "local",
        "via": "cli",
        "matched": 2,
        "not_found_blocked": 0,
    }

    token = parse_qs(urlparse(result.handouts[0].link).query)["token"][0]
    user = await passwords.activate(db, token, NEW_PASSWORD)
    assert (user.id, user.status) == (lead.id, UserStatus.ACTIVE), "входит локально по ссылке"

    with pytest.raises(switch.SwitchRefused):
        await switch.to_local(db, redis_client, os_user="ops")


async def test_letters_go_after_commit(
    db_session: AsyncSession, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(passwords, "smtp_configured", lambda _db: _true())
    monkeypatch.setattr(tasks, "enqueue_email", lambda kind, to, _f: sent.append(
        (kind, to[0].email)) or 1)  # fmt: skip
    await support.configure(db_session)
    await _ad_user(db_session, "mail", email="mail@corp.local")
    await _ad_user(db_session, "nomail")
    result = await switch.to_local(db_session, redis_client, os_user="ops")
    assert (result.emailed, [h.login for h in result.handouts]) == (1, ["nomail"])
    assert sent == [], "до commit писем нет"
    await deliver_events(db_session)
    assert sent == [("password_setup", "mail@corp.local")]


async def _true() -> bool:
    return True
