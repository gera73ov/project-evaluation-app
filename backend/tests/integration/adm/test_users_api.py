"""ADM-006: пользователи в админке администратора (7.5, FR-AUTH-LOC-01, FR-2FA-03, FR-SESS-05,
BR-ROLE-08, BR-PRJ-07, SEC-AUTHZ-06, FR-AUTH-AD-07)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import (
    AuthTokenKind,
    ProjectRole,
    SystemRole,
    UserSource,
    UserStatus,
)
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import AuthToken, BackupCode, User, UserRole
from tests.integration.auth.helpers import make_user
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5")]


async def _audit(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"), {"e": event}
    )
    return [r[0] for r in rows.all()]


async def _step_up(world: World, actor: Actor) -> None:
    loaded: Any = await world.service.load(actor.sid)
    record = loaded.record
    await world.service.update(world.db, actor.sid, record, step_up_until=world.service.now() + 300)


async def _roles(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))
    return {r.value for r in rows}


@pytest.mark.spec("FR-AUTH-LOC-01")
async def test_create_local_user_with_activation_link(
    world: World, db_session: AsyncSession
) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    body = {"login": "N.Petrova", "full_name": " Н. Петрова ", "roles": ["moderator"]}
    created = await admin.post("/admin/users", json=body)
    assert created.status_code == 201, created.text
    data = created.json()
    user = data["user"]
    assert (user["login"], user["full_name"], user["email"]) == ("N.Petrova", "Н. Петрова", None)
    assert user["status"] == "pending_password"
    assert user["system_roles"] == [{"role": "moderator", "source": "manual"}]
    # без email ссылка показывается на экране (FR-AUTH-LOC-01)
    assert data["activation"]["emailed"] is False
    assert "/activate?token=" in data["activation"]["activation_url"]
    token = await db_session.scalar(
        select(AuthToken).where(
            AuthToken.user_id == uuid.UUID(user["id"]), AuthToken.kind == AuthTokenKind.ACTIVATION
        )
    )
    assert token is not None
    [entry] = [d for d in await _audit(db_session, "users.created") if d["roles"] == ["moderator"]]
    assert entry["source"] == "admin_local"

    # логин уникален без учёта регистра, email уникален
    dup = await admin.post("/admin/users", json={**body, "login": "n.petrova"})
    assert (dup.status_code, dup.json()["code"], dup.json()["field"]) == (
        409,
        "ALREADY_EXISTS",
        "login",
    )
    first = await admin.post(
        "/admin/users", json={"login": "a.b", "full_name": "А", "email": "x@corp.ru", "roles": []}
    )
    assert first.status_code == 201, first.text
    second = await admin.post(
        "/admin/users", json={"login": "a.c", "full_name": "А", "email": "X@corp.ru", "roles": []}
    )
    assert (second.status_code, second.json()["field"]) == (409, "email")
    bad = await admin.post("/admin/users", json={**body, "login": "ив"})
    assert (bad.status_code, bad.json()["code"]) == (422, "VALIDATION_FAILED")
    admin_role = await admin.post("/admin/users", json={**body, "login": "z.z", "roles": ["admin"]})
    assert admin_role.status_code == 422


async def test_list_hides_system_accounts_and_filters(
    world: World, db_session: AsyncSession
) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    superadmin = await make_user(db_session, SystemRole.SUPERADMIN)
    auditor = await make_user(db_session, SystemRole.SECURITY_AUDITOR)
    moderator = await make_user(db_session, SystemRole.MODERATOR)
    blocked = await make_user(db_session, status=UserStatus.BLOCKED)

    seen: list[dict[str, Any]] = []
    cursor = None
    while True:
        url = "/admin/users?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = (await admin.get(url)).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    ids = {u["id"] for u in seen}
    assert str(moderator.id) in ids
    assert str(blocked.id) in ids
    assert str(superadmin.id) not in ids
    assert str(auditor.id) not in ids
    names = [u["full_name"] for u in seen]
    assert names == sorted(names)

    for hidden in (superadmin, auditor):
        response = await admin.get(f"/admin/users/{hidden.id}")
        assert response.status_code == 404

    by_role = (await admin.get("/admin/users?role=moderator")).json()["items"]
    assert [u["id"] for u in by_role] == [str(moderator.id)]
    by_status = (await admin.get("/admin/users?status=blocked")).json()["items"]
    assert [u["id"] for u in by_status] == [str(blocked.id)]
    by_q = (await admin.get(f"/admin/users?q={moderator.login[2:]}")).json()["items"]
    assert [u["id"] for u in by_q] == [str(moderator.id)]
    card = (await admin.get(f"/admin/users/{blocked.id}")).json()
    assert (card["status"], card["block_reason"]) == ("blocked", "manual")

    forged = await admin.get("/admin/users?cursor=abc")
    assert (forged.status_code, forged.json()["code"]) == (400, "CURSOR_INVALID")
    user = await world.actor()
    assert (await user.get("/admin/users")).status_code == 403


@pytest.mark.spec("SEC-AUTHZ-06")
@pytest.mark.spec("BR-ROLE-08")
async def test_patch_profile_and_roles(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    target = await make_user(db_session, SystemRole.MODERATOR)
    response = await admin.patch(
        f"/admin/users/{target.id}",
        json={
            "full_name": "Новое Имя",
            "email": "new@corp.ru",
            "roles": ["presale", "presale_head"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Новое Имя"
    assert await _roles(db_session, target.id) == {"presale", "presale_head"}
    [changed] = list(await _audit(db_session, "users.roles.changed"))
    assert changed == {"added": ["presale", "presale_head"], "removed": ["moderator"],
                       "source": "manual"}  # fmt: skip
    [updated] = await _audit(db_session, "users.updated")
    assert updated["changes"]["email"] == [None, "new@corp.ru"]

    # свои роли не меняет никто; роль администратора у другого администратора не трогается
    own = await admin.patch(f"/admin/users/{admin.id}", json={"roles": ["moderator"]})
    assert (own.status_code, own.json()["code"]) == (403, "FORBIDDEN")
    other_admin = await make_user(db_session, SystemRole.ADMIN)
    granted = await admin.patch(f"/admin/users/{other_admin.id}", json={"roles": ["moderator"]})
    assert granted.status_code == 200, granted.text
    assert await _roles(db_session, other_admin.id) == {"admin", "moderator"}
    renamed = await admin.patch(f"/admin/users/{other_admin.id}", json={"email": "a@b.ru"})
    assert (renamed.status_code, renamed.json()["code"]) == (403, "FORBIDDEN")

    # снятие «Модератора» не исключает из проектов (BR-ROLE-08)
    moderator = await world.actor(SystemRole.MODERATOR)
    await create_project(world, moderator)
    removed = await admin.patch(f"/admin/users/{moderator.id}", json={"roles": []})
    assert removed.status_code == 200
    still = await db_session.scalar(
        select(ProjectMember.id).where(ProjectMember.user_id == moderator.id)
    )
    assert still is not None


@pytest.mark.spec("FR-AUTH-AD-07")
async def test_ad_group_roles_locked_when_mapping_enabled(
    world: World, db_session: AsyncSession
) -> None:
    from tests.integration.auth.conftest import set_setting

    admin = await world.actor(SystemRole.ADMIN)
    ad_user = await make_user(db_session, source=UserSource.AD)
    await set_setting(db_session, "auth.ad.role_mapping", {"enabled": True, "mappings": []})
    locked = await admin.patch(f"/admin/users/{ad_user.id}", json={"roles": ["moderator"]})
    assert (locked.status_code, locked.json()["code"]) == (409, "ROLE_INCOMPATIBLE")
    head = await admin.patch(f"/admin/users/{ad_user.id}", json={"roles": ["presale_head"]})
    assert head.status_code == 200, head.text


@pytest.mark.spec("FR-SESS-05")
@pytest.mark.spec("BR-PRJ-07")
async def test_block_and_unblock(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    assert (await moderator.get("/me")).status_code == 200

    blocked = await admin.post(f"/admin/users/{moderator.id}/block", json={"reason": "Уволен"})
    assert blocked.status_code == 200, blocked.text
    assert (blocked.json()["status"], blocked.json()["block_reason"]) == ("blocked", "manual")
    assert (await moderator.get("/me")).status_code == 401  # сессия завершена
    assert await world.service.active_hashes(moderator.id) == []
    project = await db_session.get(Project, project_id)
    assert project is not None
    assert project.no_moderator_since is not None
    member = await db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.MODERATOR
        )
    )
    assert member is not None  # из проекта не исключён
    notified = await db_session.execute(
        text(
            "SELECT 1 FROM notifications WHERE user_id = :u AND kind = 'project_without_moderator'"
        ),
        {"u": admin.id},
    )
    assert notified.first() is not None
    [entry] = await _audit(db_session, "users.blocked")
    assert entry["block_reason"] == "manual"
    again = await admin.post(f"/admin/users/{moderator.id}/block", json={})
    assert again.status_code == 200
    assert len(await _audit(db_session, "users.blocked")) == 1

    unblocked = await admin.post(f"/admin/users/{moderator.id}/unblock")
    assert (unblocked.status_code, unblocked.json()["status"]) == (200, "active")
    await db_session.refresh(project)
    assert project.no_moderator_since is None
    [entry] = await _audit(db_session, "users.unblocked")
    assert entry == {"previous_reason": "manual", "automatic": False}

    # не активированный остаётся «ждёт пароль»; себя и администратора блокировать нельзя
    pending = await make_user(
        db_session, password_hash_value=None, status=UserStatus.PENDING_PASSWORD
    )
    await admin.post(f"/admin/users/{pending.id}/block", json={})
    back = await admin.post(f"/admin/users/{pending.id}/unblock")
    assert back.json()["status"] == "pending_password"
    self_block = await admin.post(f"/admin/users/{admin.id}/block", json={})
    assert self_block.status_code == 403
    other_admin = await make_user(db_session, SystemRole.ADMIN)
    assert (await admin.post(f"/admin/users/{other_admin.id}/block", json={})).status_code == 403


@pytest.mark.spec("FR-2FA-03")
async def test_reset_password_and_totp_need_step_up(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    target = await make_user(db_session)
    target.email = f"{target.login}@corp.ru"
    target.totp_enabled = True
    target.totp_secret_enc = b"secret"
    db_session.add(BackupCode(user_id=target.id, code_hash="x" * 64))
    await db_session.flush()
    victim = await world.session_for(target.id)

    no_step_up = await admin.post(f"/admin/users/{target.id}/reset-password")
    assert (no_step_up.status_code, no_step_up.json()["code"]) == (403, "STEP_UP_REQUIRED")
    await _step_up(world, admin)

    link = await admin.post(f"/admin/users/{target.id}/reset-password")
    assert link.status_code == 200, link.text
    body = link.json()
    # SMTP в тестах не настроен — ссылка на экран
    assert body["emailed"] is False
    assert "/password/reset?token=" in body["activation_url"]
    [issued] = await _audit(db_session, "auth.password.reset_issued")
    assert issued == {"target_roles": [], "delivery": "screen"}

    reset = await admin.post(f"/admin/users/{target.id}/reset-totp")
    assert reset.status_code == 204, reset.text
    await db_session.refresh(target)
    assert (target.totp_enabled, target.totp_secret_enc) == (False, None)
    codes = await db_session.scalar(select(BackupCode.id).where(BackupCode.user_id == target.id))
    assert codes is None
    assert (await victim.get("/me")).status_code == 401
    assert len(await _audit(db_session, "auth.mfa.reset")) == 1

    pending = await make_user(
        db_session, password_hash_value=None, status=UserStatus.PENDING_PASSWORD
    )
    activation = await admin.post(f"/admin/users/{pending.id}/reset-password")
    assert "/activate?token=" in activation.json()["activation_url"]
    ad_user = await make_user(db_session, source=UserSource.AD)
    assert (await admin.post(f"/admin/users/{ad_user.id}/reset-password")).status_code == 403
    other_admin = await make_user(db_session, SystemRole.ADMIN)
    assert (await admin.post(f"/admin/users/{other_admin.id}/reset-totp")).status_code == 403


async def test_anonymized_account_is_not_editable(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    user = await make_user(db_session, status=UserStatus.BLOCKED)
    db_user = await db_session.get(User, user.id)
    assert db_user is not None
    db_user.status = UserStatus.ANONYMIZED
    db_user.block_reason = None
    db_user.anonymized_no = 999_001
    await db_session.flush()
    assert (await admin.get(f"/admin/users/{user.id}")).json()["status"] == "anonymized"
    for path in ("block", "unblock"):
        assert (await admin.post(f"/admin/users/{user.id}/{path}", json={})).status_code == 404
    assert (
        await admin.patch(f"/admin/users/{user.id}", json={"full_name": "X"})
    ).status_code == 404
