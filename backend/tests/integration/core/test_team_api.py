"""CORE-012: команда проекта — роли и системные роли, лимит пресейла, последний модератор (G-09),
несовместимые роли, авто-добавление дисциплины, аудит самоназначения администратора, событие
``member.updated``, замена заблокированного, ``no_moderator_since`` (FR-PRJ-01, BR-ROLE-04..08,
FR-ADM-05, BR-ADM-03, BR-PRJ-07)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole, UserBlockReason, UserStatus
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project, ProjectDiscipline
from estimator.db.models.users import User, UserRole
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services import team
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.helpers import audit_details, create_project, discipline

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PRJ-01"), pytest.mark.spec("3.2")]


def _m(user: Actor, role: str, discipline_id: uuid.UUID | None = None, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"user_id": str(user.id), "role": role}
    if discipline_id is not None:
        out["discipline_id"] = str(discipline_id)
    return out | kw


async def _block(db: AsyncSession, user_id: uuid.UUID) -> None:
    row = await db.get(User, user_id)
    row.status, row.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db.flush()


@pytest.mark.spec("BR-ROLE-07")
async def test_put_members_rules(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    url = f"/projects/{pid}/members"
    backend = await discipline(db_session, "Бэкенд")
    expert = await world.actor()

    last = await moderator.put(url, json={"members": [_m(expert, "expert", backend)]})
    assert (last.status_code, last.json()["code"]) == (409, "LAST_MODERATOR")

    plain = await world.actor()
    no_role = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(plain, "presale")]}
    )
    assert (no_role.status_code, no_role.json()["code"]) == (422, "MEMBER_ROLE_REQUIRED")
    assert no_role.json()["required_role"] == "presale"
    not_moderator = await moderator.put(url, json={"members": [_m(plain, "moderator")]})
    assert not_moderator.json()["required_role"] == "moderator"
    head = await world.actor(SystemRole.PRESALE_HEAD)
    head_try = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(head, "moderator")]}
    )
    assert head_try.status_code == 422  # руководитель пресейла — только сам (CORE-071)

    presales = [await world.actor(SystemRole.PRESALE) for _ in range(4)]
    too_many = await moderator.put(
        url, json={"members": [_m(moderator, "moderator")] + [_m(p, "presale") for p in presales]}
    )
    assert (too_many.status_code, too_many.json()["code"]) == (422, "MEMBER_LIMIT")
    assert (too_many.json()["role"], too_many.json()["limit"]) == ("presale", 3)

    auditor = await world.actor(SystemRole.SECURITY_AUDITOR)
    clash = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(auditor, "expert", backend)]}
    )
    assert (clash.status_code, clash.json()["code"]) == (409, "ROLE_INCOMPATIBLE")
    assert clash.json()["conflicting_roles"] == ["security_auditor"]

    shape = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(expert, "expert")]}
    )
    assert (shape.status_code, shape.json()["code"]) == (422, "VALIDATION_FAILED")
    reviewer = await moderator.put(
        url, json={"members": [_m(moderator, "moderator", is_reviewer=True)]}
    )
    assert reviewer.status_code == 422
    blocked = await world.actor()
    await _block(db_session, blocked.id)
    no_blocked = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(blocked, "expert", backend)]}
    )
    assert no_blocked.status_code == 422

    # модератор + эксперт (BR-ROLE-04), эксперт на две дисциплины (BR-ROLE-05), ревьюер;
    # дисциплина, которой не было, добавляется вместе с ветками (FR-PRJ-04)
    qa = await discipline(db_session, "QA")
    ok = await moderator.put(
        url,
        json={
            "members": [
                _m(moderator, "moderator"),
                _m(moderator, "expert", backend),
                _m(expert, "expert", backend, is_reviewer=True),
                _m(expert, "expert", qa),
                _m(presales[0], "presale"),
            ]
        },
    )
    assert ok.status_code == 200, ok.text
    items = ok.json()["items"]
    assert [i["role"] for i in items] == ["moderator", "presale", "expert", "expert", "expert"]
    assert {
        (i["user"]["id"], i["discipline_id"], i["is_reviewer"])
        for i in items
        if i["role"] == "expert"
    } == {
        (str(moderator.id), str(backend), False),
        (str(expert.id), str(backend), True),
        (str(expert.id), str(qa), False),
    }
    assert all(i["status"] == "active" for i in items)
    present = set(
        (
            await db_session.scalars(
                select(ProjectDiscipline.discipline_id).where(ProjectDiscipline.project_id == pid)
            )
        ).all()
    )
    assert present == {backend, qa}
    tree = (await moderator.get(f"/projects/{pid}/tree")).json()
    assert len([n for n in tree["nodes"] if n["kind"] == "discipline"]) == 4
    assert (await expert.get(url)).status_code == 404  # эксперт в «Подготовке» проекта не видит
    assert (await moderator.get(url)).json()["items"] == items

    # уже назначенный модератор без системной роли остаётся (BR-ROLE-08)
    plain_moderator = await world.actor(SystemRole.MODERATOR)
    await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(plain_moderator, "moderator")]}
    )
    await db_session.execute(
        UserRole.__table__.delete().where(UserRole.user_id == plain_moderator.id)
    )
    kept = await moderator.put(
        url, json={"members": [_m(moderator, "moderator"), _m(plain_moderator, "moderator")]}
    )
    assert kept.status_code == 200


@pytest.mark.spec("BR-ADM-03")
@pytest.mark.spec("Q-25")
async def test_audit_and_events(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    admin = await world.actor(SystemRole.ADMIN, SystemRole.MODERATOR)
    pid = await create_project(world, admin)
    url = f"/projects/{pid}/members"
    expert = await world.actor()
    backend = await discipline(db_session, "Бэкенд")
    await deliver_events(db_session)
    events.events.clear()
    first = await admin.put(
        url,
        json={
            "members": [
                _m(admin, "moderator"),
                _m(admin, "expert", backend),
                _m(expert, "expert", backend),
            ]
        },
    )
    assert first.status_code == 200, first.text
    mine = {
        (i["role"], i["added_by_admin_self"])
        for i in first.json()["items"]
        if i["user"]["id"] == str(admin.id)
    }
    assert mine == {("moderator", True), ("expert", True)}
    second = await admin.put(
        url,
        json={"members": [_m(admin, "moderator"), _m(expert, "expert", backend, is_reviewer=True)]},
    )
    assert second.status_code == 200
    unchanged = await admin.put(
        url,
        json={"members": [_m(admin, "moderator"), _m(expert, "expert", backend, is_reviewer=True)]},
    )
    assert unchanged.status_code == 200
    await deliver_events(db_session)
    member_events = [
        e["data"] for e in events.on(f"project:{pid}") if e["event"] == "member.updated"
    ]
    assert member_events == [
        {"user_ids": sorted([str(admin.id), str(expert.id)]), "change": "added"},
        {"user_ids": sorted([str(admin.id), str(expert.id)]), "change": "updated"},
    ]
    entries = await audit_details(db_session, "project.team.changed", pid)
    ops = [(d["op"], d["member_user_id"], d["role"], d["added_by_admin_self"]) for d in entries]
    assert ("added", str(admin.id), "expert", True) in ops
    assert ("added", str(expert.id), "expert", False) in ops
    assert ("removed", str(admin.id), "expert", True) in ops
    assert ("updated", str(expert.id), "expert", False) in ops
    assert all(d["via"] == "team" for d in entries)


@pytest.mark.spec("BR-PRJ-01")
async def test_assigned_notification_after_launch(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    other = await world.actor(SystemRole.MODERATOR)
    await moderator.put(
        f"/projects/{pid}/members",
        json={"members": [_m(moderator, "moderator"), _m(other, "moderator")]},
    )

    async def kinds(user_id: uuid.UUID) -> list[str]:
        stmt = select(Notification.kind).where(Notification.user_id == user_id)
        return list((await db_session.scalars(stmt)).all())

    assert await kinds(other.id) == ["assigned_to_project"]  # модератору — сразу
    assert (
        await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    ).status_code == 200
    late = await world.actor()
    await moderator.put(
        f"/projects/{pid}/members",
        json={
            "members": [
                _m(moderator, "moderator"),
                _m(other, "moderator"),
                _m(late, "expert", backend),
            ]
        },
    )
    assert await kinds(late.id) == ["assigned_to_project"]  # назначен в идущий проект — сразу


@pytest.mark.spec("FR-ADM-05")
@pytest.mark.spec("BR-PRJ-07")
async def test_replace_blocked_member(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    url = f"/projects/{pid}/members"
    backend = await discipline(db_session, "Бэкенд")
    gone = await world.actor(SystemRole.MODERATOR)
    await moderator.put(
        url,
        json={
            "members": [
                _m(moderator, "moderator"),
                _m(gone, "moderator"),
                _m(gone, "expert", backend, is_reviewer=True),
            ]
        },
    )
    newcomer = await world.actor()
    active = await moderator.post(
        f"{url}/{gone.id}/replace", json={"replacement_user_id": str(newcomer.id)}
    )
    assert (active.status_code, active.json()["code"]) == (
        422,
        "VALIDATION_FAILED",
    )  # не заблокирован

    await _block(db_session, gone.id)
    listed = (await moderator.get(url)).json()["items"]
    assert {i["status"] for i in listed if i["user"]["id"] == str(gone.id)} == {"blocked"}
    no_role = await moderator.post(
        f"{url}/{gone.id}/replace", json={"replacement_user_id": str(newcomer.id)}
    )
    assert (no_role.status_code, no_role.json()["code"]) == (422, "MEMBER_ROLE_REQUIRED")
    stranger = await moderator.post(
        f"{url}/{uuid.uuid4()}/replace", json={"replacement_user_id": str(newcomer.id)}
    )
    assert stranger.status_code == 404

    heir = await world.actor(SystemRole.MODERATOR)
    replaced = await moderator.post(
        f"{url}/{gone.id}/replace", json={"replacement_user_id": str(heir.id)}
    )
    assert replaced.status_code == 200, replaced.text
    rows = {
        (i["user"]["id"], i["role"], i["discipline_id"], i["is_reviewer"])
        for i in replaced.json()["items"]
    }
    assert rows == {
        (str(moderator.id), "moderator", None, False),
        (str(heir.id), "moderator", None, False),
        (str(heir.id), "expert", str(backend), True),
    }
    note = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == heir.id, Notification.kind == "member_replaced"
            )
        )
    ).one()
    assert note.payload["replaced_user_id"] == str(gone.id)
    via = {
        d["via"]
        for d in await audit_details(db_session, "project.team.changed", pid)
        if d["member_user_id"] in (str(gone.id), str(heir.id))
    }
    assert "replace" in via

    # все модераторы заблокированы — «Проект без модератора» и уведомление администраторам
    admin = await world.actor(SystemRole.ADMIN)
    project = await db_session.get(Project, pid)
    await _block(db_session, moderator.id)
    await _block(db_session, heir.id)
    await team.refresh_no_moderator(db_session, project)
    assert project.no_moderator_since is not None
    since = project.no_moderator_since
    await team.refresh_no_moderator(db_session, project)
    assert project.no_moderator_since == since
    sent = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == admin.id, Notification.kind == "project_without_moderator"
            )
        )
    ).all()
    assert len(sent) == 1
    row = await db_session.get(User, heir.id)
    row.status, row.block_reason = UserStatus.ACTIVE, None
    await db_session.flush()
    await team.refresh_no_moderator(db_session, project)
    assert project.no_moderator_since is None
