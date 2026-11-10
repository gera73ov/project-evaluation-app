"""ADM-012: «Заменить участника» во всех проектах — dry run с проверкой ролей замены, перенос ролей,
дисциплин и ревьюерства, переадресация открытых вопросов, уведомления и аудит (FR-ADM-05, Q-29,
TC-ADM-01)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.discussions import Notification
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import create_project
from tests.integration.core.test_nodes_api import _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-ADM-05"), pytest.mark.spec("TC-ADM-01")]


async def _kinds(db: AsyncSession, user: Actor) -> set[str]:
    return set(await db.scalars(select(Notification.kind).where(Notification.user_id == user.id)))


async def test_replace_everywhere(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    leaving = await world.actor(SystemRole.MODERATOR)
    members = [
        {"user_id": str(s.moderator.id), "role": "moderator"},
        {"user_id": str(leaving.id), "role": "expert", "discipline_id": str(s.backend),
         "is_reviewer": True},
        {"user_id": str(s.frontend_expert.id), "role": "expert",
         "discipline_id": str(s.frontend)},
    ]  # fmt: skip
    put = await s.moderator.put(f"/projects/{s.pid}/members", json={"members": members})
    assert put.status_code == 200, put.text
    own = await create_project(world, leaving)  # здесь он модератор
    asked = await s.moderator.post(
        f"/projects/{s.pid}/threads",
        json={"node_id": None, "body": "Какие SLA?",
              "addressees": [{"target_type": "user", "target_id": str(leaving.id)}]},
    )  # fmt: skip
    assert asked.status_code == 201, asked.text

    heir = await world.actor()  # без роли «Модератор»
    admin = await world.actor(SystemRole.ADMIN)
    url = f"/admin/users/{leaving.id}/replace"
    dry = await admin.post(url, json={"replacement_user_id": str(heir.id)})
    assert dry.status_code == 200, dry.text
    report = {p["project_id"]: p for p in dry.json()["projects"]}
    assert dry.json()["applied"] is False
    assert report[str(s.pid)]["applicable"] is True
    assert report[str(s.pid)]["open_questions"] == 1
    assert report[str(s.pid)]["roles"] == [
        {"role": "expert", "discipline_id": str(s.backend), "is_reviewer": True}
    ]
    assert (report[str(own)]["applicable"], report[str(own)]["problem"]) == (
        False, "replacement_lacks_moderator_role",
    )  # fmt: skip

    stranger = await admin.post(url, json={"replacement_user_id": str(heir.id), "dry_run": False,
                                           "project_ids": [str(uuid.uuid4())]})  # fmt: skip
    assert stranger.status_code == 422
    same = await admin.post(url, json={"replacement_user_id": str(leaving.id)})
    assert same.status_code == 422

    done = await admin.post(
        url,
        json={"replacement_user_id": str(heir.id), "dry_run": False,
              "project_ids": [str(s.pid), str(own)]},
    )  # fmt: skip
    assert done.status_code == 200, done.text
    assert done.json()["applied"] is True
    team = (await s.moderator.get(f"/projects/{s.pid}/members")).json()["items"]
    rows = {(m["user"]["id"], m["role"], m.get("discipline_id"), m["is_reviewer"]) for m in team}
    assert (str(heir.id), "expert", str(s.backend), True) in rows
    assert all(m["user"]["id"] != str(leaving.id) for m in team)
    untouched = (await leaving.get(f"/projects/{own}/members")).json()["items"]
    assert [m["user"]["id"] for m in untouched] == [str(leaving.id)]  # строка не применена

    to_heir = await heir.get(f"/projects/{s.pid}/threads", params={"addressee": "me"})
    assert [t["id"] for t in to_heir.json()["items"]] == [asked.json()["id"]]
    assert {"question_redirected", "member_replaced"} <= await _kinds(db_session, heir)
    assert "member_replaced" in await _kinds(db_session, s.moderator)
    [details] = (
        await db_session.execute(
            text("SELECT details FROM audit.audit_log"
                 " WHERE event_type = 'users.replaced_everywhere' AND object_id = :u"),
            {"u": str(leaving.id)},
        )
    ).scalars().all()  # fmt: skip
    assert (details["projects_applied"], details["projects_skipped"]) == (1, 1)
    assert details["questions_redirected"] == 1

    moderator = await world.actor(SystemRole.MODERATOR)
    assert (
        await moderator.post(url, json={"replacement_user_id": str(heir.id)})
    ).status_code == 403
