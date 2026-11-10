"""ADM-004: суперадминистраторы, администраторы и аудиторы ИБ (FR-SA-05, FR-2FA-03, BR-ROLE-02,
BR-ROLE-03, Q-07, SEC-AUTH-05, SEC-AUTH-07)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole, UserStatus
from estimator.db.models.users import User, UserRole
from tests.integration.adm.helpers import audit_details, step_up
from tests.integration.auth.helpers import make_user
from tests.integration.core.conftest import Actor, World

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SA-05")]


async def _root(world: World) -> Actor:
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    return root


async def _roles(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))
    return {r.value for r in rows}


def _new(role: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    return {"login": f"sa.{tag}", "email": f"{tag}@corp.ru", "full_name": f"Учётка {tag}",
            "role": role}  # fmt: skip


@pytest.mark.spec("BR-ROLE-03")
@pytest.mark.spec("Q-07")
async def test_superadmins_two_to_three(world: World, db_session: AsyncSession) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    body = _new("superadmin")
    denied = await root.post("/system/admins", json=body)
    assert (denied.status_code, denied.json()["code"]) == (403, "STEP_UP_REQUIRED")
    await step_up(world, root)
    created = await root.post("/system/admins", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["activation_url"]  # без SMTP — ссылка на экран
    second = await db_session.scalar(select(User).where(User.login == body["login"]))
    assert second is not None
    assert second.status == UserStatus.PENDING_PASSWORD
    assert await _roles(db_session, second.id) == {"superadmin"}
    third = await root.post("/system/admins", json=_new("superadmin"))
    assert third.status_code == 201
    fourth = await root.post("/system/admins", json=_new("superadmin"))
    assert (fourth.status_code, fourth.json()["code"]) == (409, "SUPERADMIN_LIMIT")
    dup = await root.post("/system/admins", json={**_new("admin"), "login": body["login"].upper()})
    assert (dup.status_code, dup.json()["code"]) == (409, "ALREADY_EXISTS")
    bad = await root.post("/system/admins", json={**_new("admin"), "login": "с пробелом"})
    assert bad.status_code == 422
    events = await audit_details(db_session, "system.privileged_account.changed")
    assert {"role": "superadmin", "op": "created"} in events

    listed = (await root.get("/system/admins")).json()["items"]
    mine = next(a for a in listed if a["login"] == body["login"])
    assert (mine["roles"], mine["status"]) == (["superadmin"], "pending_password")


@pytest.mark.spec("BR-ROLE-02")
async def test_grant_revoke_block_demote(world: World, db_session: AsyncSession) -> None:
    root = await _root(world)
    person = await make_user(db_session)
    moderator = await make_user(db_session, SystemRole.MODERATOR)
    path = f"/system/admins/{person.id}"

    auditor = await root.patch(path, json={"roles": ["security_auditor"]})
    assert auditor.status_code == 200, auditor.text
    assert auditor.json()["roles"] == ["security_auditor"]
    both = await root.patch(path, json={"roles": ["security_auditor", "admin"]})
    assert (both.status_code, both.json()["code"]) == (409, "ROLE_INCOMPATIBLE")
    clash = await root.patch(f"/system/admins/{moderator.id}", json={"roles": ["security_auditor"]})
    assert (clash.status_code, clash.json()["code"]) == (409, "ROLE_INCOMPATIBLE")
    promote = await root.patch(f"/system/admins/{moderator.id}", json={"roles": ["admin"]})
    assert promote.status_code == 200
    assert await _roles(db_session, moderator.id) == {"moderator", "admin"}
    to_super = await root.patch(path, json={"roles": ["superadmin"]})
    assert (to_super.status_code, to_super.json()["code"]) == (403, "FORBIDDEN")

    blocked = await root.patch(f"/system/admins/{moderator.id}", json={"status": "blocked"})
    assert blocked.json()["status"] == "blocked"
    back = await root.patch(f"/system/admins/{moderator.id}", json={"status": "active"})
    assert back.json()["status"] == "active"
    demoted = await root.delete(f"/system/admins/{moderator.id}")
    assert demoted.status_code == 204
    assert await _roles(db_session, moderator.id) == {"moderator"}
    assert (await root.delete(f"/system/admins/{moderator.id}")).status_code == 404

    ops = [(e["role"], e["op"]) for e in
           await audit_details(db_session, "system.privileged_account.changed")]  # fmt: skip
    assert ops == [
        ("security_auditor", "granted"), ("admin", "granted"), ("admin", "blocked"),
        ("admin", "unblocked"), ("admin", "revoked"),
    ]  # fmt: skip
    own = await root.patch(f"/system/admins/{root.id}", json={"status": "blocked"})
    assert own.status_code == 403
    assert (await root.patch(f"/system/admins/{uuid.uuid4()}", json={})).status_code == 404


@pytest.mark.spec("FR-2FA-03")
@pytest.mark.spec("SEC-AUTH-05")
async def test_reset_credentials_of_privileged(world: World, db_session: AsyncSession) -> None:
    root = await world.actor(SystemRole.SUPERADMIN)
    admin = await make_user(db_session, SystemRole.ADMIN)
    admin.totp_enabled, admin.totp_secret_enc = True, b"\x01" * 40
    await db_session.flush()
    plain = await make_user(db_session, SystemRole.MODERATOR)
    path = f"/system/users/{admin.id}"
    denied = await root.post(f"{path}/reset-password")
    assert (denied.status_code, denied.json()["code"]) == (403, "STEP_UP_REQUIRED")
    await step_up(world, root)
    link = await root.post(f"{path}/reset-password")
    assert link.status_code == 200, link.text
    assert link.json()["activation_url"]
    totp = await root.post(f"{path}/reset-totp")
    assert totp.status_code == 204
    await db_session.refresh(admin)
    assert admin.totp_enabled is False
    [entry] = await audit_details(db_session, "auth.password.reset_issued")
    assert entry["target_roles"] == ["admin"]
    assert (await root.post(f"/system/users/{plain.id}/reset-totp")).status_code == 404
    assert (await root.post(f"/system/users/{root.id}/reset-password")).status_code == 403
    administrator = await world.actor(SystemRole.ADMIN)
    assert (await administrator.get("/system/admins")).status_code == 403
