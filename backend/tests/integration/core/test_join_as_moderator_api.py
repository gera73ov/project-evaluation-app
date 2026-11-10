"""CORE-071: «Стать модератором проекта» — руководитель пресейла добавляет только себя, кроме
«Архива»; уведомление модераторам, аудит; ограничения после входа (FR-PORT-03, R-06, G-21)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import audit_details, create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PORT-03"), pytest.mark.spec("R-06")]


def _m(user: Actor, role: str) -> dict[str, Any]:
    return {"user_id": str(user.id), "role": role}


def _moderators(body: dict[str, Any]) -> set[str]:
    return {m["user"]["id"] for m in body["items"] if m["role"] == "moderator"}


async def _kinds(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    stmt = select(Notification.kind).where(Notification.user_id == user_id)
    return list(await db.scalars(stmt))


async def test_join_notifies_and_audits(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    head = await world.actor(SystemRole.PRESALE_HEAD)
    url = f"/projects/{pid}/join-as-moderator"

    joined = await head.post(url)
    assert joined.status_code == 200, joined.text
    assert _moderators(joined.json()) == {str(moderator.id), str(head.id)}
    assert "presale_head_joined" in await _kinds(db_session, moderator.id)
    assert "presale_head_joined" not in await _kinds(db_session, head.id)
    assert len(await audit_details(db_session, "project.joined_as_moderator", pid)) == 1
    team = await audit_details(db_session, "project.team.changed", pid)
    [row] = [r for r in team if r["member_user_id"] == str(head.id)]
    assert (row["op"], row["via"]) == ("added", "join_as_moderator")

    again = await head.post(url)  # повтор ничего не меняет
    assert again.status_code == 200
    assert len(await audit_details(db_session, "project.joined_as_moderator", pid)) == 1

    assert (await moderator.post(url)).status_code == 403  # только руководитель пресейла


@pytest.mark.spec("SEC-AUTHZ-05")
async def test_limits_after_join(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    head = await world.actor(SystemRole.PRESALE_HEAD)
    other = await world.actor(SystemRole.MODERATOR)
    members = f"/projects/{pid}/members"
    assert (await head.put(members, json={"members": [_m(head, "moderator")]})).status_code == 403
    assert (await head.post(f"/projects/{pid}/join-as-moderator")).status_code == 200

    add = await head.put(
        members,
        json={"members": [_m(moderator, "moderator"), _m(head, "moderator"),
                          _m(other, "moderator")]},
    )  # fmt: skip
    assert (add.status_code, add.json()["code"]) == (403, "FORBIDDEN")
    drop = await head.put(members, json={"members": [_m(head, "moderator")]})
    assert (drop.status_code, drop.json()["code"]) == (403, "FORBIDDEN")

    leave = await head.put(members, json={"members": [_m(moderator, "moderator")]})
    assert leave.status_code == 200, leave.text
    assert _moderators(leave.json()) == {str(moderator.id)}


async def test_archived_project(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await db_session.execute(
        update(Project).where(Project.id == pid).values(status=ProjectStatus.ARCHIVED)
    )
    await db_session.flush()
    head = await world.actor(SystemRole.PRESALE_HEAD)
    archived = await head.post(f"/projects/{pid}/join-as-moderator")
    assert (archived.status_code, archived.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")
