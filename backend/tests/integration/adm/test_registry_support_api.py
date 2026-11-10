"""ADM-010, ADM-011, ADM-005: реестры проектов, «Проекты без модератора», передача модератора,
режим поддержки (7.5, BR-PRJ-07, BR-ADM-03, FR-ADM-06, TC-ADM-02, SEC-AUTHZ-05)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project, SupportSession
from tests.integration.core.conftest import World
from tests.integration.core.helpers import create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5")]


async def _audit(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"), {"e": event}
    )
    return [r[0] for r in rows.all()]


async def _notes(db: AsyncSession, user_id: uuid.UUID, kind: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT payload FROM notifications WHERE user_id = :u AND kind = :k"),
        {"u": user_id, "k": kind},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.spec("BR-PRJ-07")
async def test_registry_without_moderator_and_transfer(
    world: World, db_session: AsyncSession
) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    other_id = await create_project(world, moderator)

    listed = (await admin.get("/admin/projects")).json()
    row = next(p for p in listed["items"] if p["id"] == str(project_id))
    assert [m["id"] for m in row["moderators"]] == [str(moderator.id)]
    assert (row["no_moderator_since"], row["days_without_moderator"]) == (None, None)
    assert "money" not in row
    assert "totals" not in row

    blocked = await admin.post(f"/admin/users/{moderator.id}/block", json={})
    assert blocked.status_code == 200
    lonely = (await admin.get("/admin/projects?without_moderator=true")).json()["items"]
    assert {p["id"] for p in lonely} == {str(project_id), str(other_id)}
    assert lonely[0]["days_without_moderator"] == 0
    assert lonely[0]["moderators"][0]["is_active"] is False
    await db_session.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(no_moderator_since=dt.datetime.now(dt.UTC) - dt.timedelta(days=3, hours=1))
    )
    lonely = (await admin.get("/admin/projects?without_moderator=true&limit=1")).json()
    assert len(lonely["items"]) == 1
    assert lonely["next_cursor"] is not None
    rest = (
        await admin.get(f"/admin/projects?without_moderator=true&cursor={lonely['next_cursor']}")
    ).json()
    days = {p["id"]: p["days_without_moderator"] for p in lonely["items"] + rest["items"]}
    assert days[str(project_id)] == 3

    # передать проект: новый модератор с системной ролью, заблокированный снимается
    newcomer = await world.actor(SystemRole.MODERATOR)
    plain = await world.actor()
    no_role = await admin.post(
        f"/admin/projects/{project_id}/moderators", json={"add_user_ids": [str(plain.id)]}
    )
    assert (no_role.status_code, no_role.json()["code"]) == (422, "MEMBER_ROLE_REQUIRED")
    last = await admin.post(
        f"/admin/projects/{project_id}/moderators", json={"remove_user_ids": [str(moderator.id)]}
    )
    assert (last.status_code, last.json()["code"]) == (409, "LAST_MODERATOR")
    moved = await admin.post(
        f"/admin/projects/{project_id}/moderators",
        json={"add_user_ids": [str(newcomer.id)], "remove_user_ids": [str(moderator.id)]},
    )
    assert moved.status_code == 200, moved.text
    moderators = [m["user"]["id"] for m in moved.json()["items"] if m["role"] == "moderator"]
    assert moderators == [str(newcomer.id)]
    project = await db_session.get(Project, project_id, populate_existing=True)
    assert project is not None
    assert project.no_moderator_since is None
    vias = {d["via"] for d in await _audit(db_session, "project.team.changed")}
    assert "transfer" in vias
    assert await _notes(db_session, newcomer.id, "assigned_to_project")

    missing = await admin.post(f"/admin/projects/{uuid.uuid4()}/moderators", json={})
    assert missing.status_code == 404
    assert (await moderator.get("/admin/projects")).status_code in (401, 403)


@pytest.mark.spec("BR-ADM-03")
async def test_admin_assigns_self_with_mark(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN, SystemRole.MODERATOR)
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    response = await admin.post(
        f"/admin/projects/{project_id}/moderators", json={"add_user_ids": [str(admin.id)]}
    )
    assert response.status_code == 200, response.text
    mine = next(m for m in response.json()["items"] if m["user"]["id"] == str(admin.id))
    assert mine["added_by_admin_self"] is True
    entry = [d for d in await _audit(db_session, "project.team.changed") if d["via"] == "transfer"]
    assert entry[-1]["added_by_admin_self"] is True


@pytest.mark.spec("FR-ADM-06")
@pytest.mark.spec("TC-ADM-02")
async def test_support_session(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    await db_session.execute(
        update(Project).where(Project.id == project_id).values(status=ProjectStatus.ARCHIVED)
    )
    await db_session.flush()
    assert (await admin.get(f"/projects/{project_id}")).status_code == 404  # без сессии не видит

    path = f"/admin/projects/{project_id}/support-session"
    assert (await admin.post(path, json={"reason": "мало"})).status_code == 422
    reason = "Проверка жалобы на расчёт итогов"
    opened = await admin.post(path, json={"reason": reason})
    assert opened.status_code == 201, opened.text
    expires = dt.datetime.fromisoformat(opened.json()["expires_at"])
    left = expires - dt.datetime.now(dt.UTC)
    assert dt.timedelta(minutes=59) < left <= dt.timedelta(minutes=60)

    # чтение — да; деньги и запись — нет
    card = await admin.get(f"/projects/{project_id}")
    assert card.status_code == 200, card.text
    assert card.json()["access"] == "support"  # жёлтая полоса
    assert card.json()["support_expires_at"] == opened.json()["expires_at"]
    granted = set(card.json()["my_permissions"])
    assert "project.read" in granted
    assert not granted & {"notes.read", "notes.write", "money.read", "project.settings.write"}
    assert (await admin.get(f"/projects/{project_id}/tree")).status_code == 200
    assert (await admin.get(f"/projects/{project_id}/money")).status_code == 403
    patched = await admin.patch(f"/projects/{project_id}", json={"name": "Чужое имя"})
    assert patched.status_code == 403

    [entry] = await _audit(db_session, "project.support_session.opened")
    assert entry["reason"] == reason
    # уведомление модераторам — и в «Архиве»
    [note] = await _notes(db_session, moderator.id, "support_session_opened")
    assert note["reason"] == reason

    # повторное открытие закрывает прежнюю сессию; истёкшая — снова 404
    again = await admin.post(path, json={"reason": reason})
    assert again.status_code == 201
    active = await db_session.scalars(
        select(SupportSession).where(
            SupportSession.project_id == project_id, SupportSession.ended_at.is_(None)
        )
    )
    assert [s.id for s in active] == [uuid.UUID(again.json()["id"])]
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=70)
    await db_session.execute(
        update(SupportSession)
        .where(SupportSession.project_id == project_id)
        .values(started_at=past, expires_at=past + dt.timedelta(minutes=60))
    )
    await db_session.flush()
    assert (await admin.get(f"/projects/{project_id}")).status_code == 404
    alien = await admin.post(
        f"/admin/projects/{uuid.uuid4()}/support-session", json={"reason": reason}
    )
    assert alien.status_code == 404


async def test_system_registry_for_superadmin(world: World) -> None:
    superadmin = await world.actor(SystemRole.SUPERADMIN)
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    listed = await superadmin.get("/system/projects")
    assert listed.status_code == 200, listed.text
    row = next(p for p in listed.json()["items"] if p["id"] == str(project_id))
    assert row["moderators"][0]["id"] == str(moderator.id)
    # CL-09: проект и дерево суперадминистратор не открывает
    assert (await superadmin.get(f"/projects/{project_id}/tree")).status_code == 404
    assert (await superadmin.get(f"/projects/{project_id}")).status_code == 404
    assert (await moderator.get("/system/projects")).status_code == 403
