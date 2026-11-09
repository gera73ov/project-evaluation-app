"""NTF-003: уведомления в приложении — гейт по статусу проекта, правила получателей, событие
``notification.created``, список «Мне» и отметка прочитанного (FR-NOTIF-01, 3.4 строки 15–16)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import (
    ProjectRole,
    ProjectStatus,
    SystemRole,
    UserBlockReason,
    UserStatus,
)
from estimator.db.models.dictionaries import Discipline
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User
from estimator.notifications import inapp
from estimator.realtime.bus.memory import InMemoryBus
from tests.integration.core.conftest import World, deliver_events

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-NOTIF-01")]


async def _project(db: AsyncSession, status: ProjectStatus) -> Project:
    project = Project(name="Портал", customer="ООО", pm_percent=Decimal(18), status=status)
    db.add(project)
    await db.flush()
    return project


async def _member(
    db: AsyncSession, project: Project, user_id: uuid.UUID, role: ProjectRole
) -> None:
    discipline = None
    if role is ProjectRole.EXPERT:
        discipline = (
            await db.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))
        ).one()
    db.add(
        ProjectMember(project_id=project.id, user_id=user_id, role=role, discipline_id=discipline)
    )
    await db.flush()


@pytest.mark.spec("3.4")
async def test_status_gate_in_preparation(world: World, db_session: AsyncSession) -> None:
    """В «Подготовке» оценочное уведомление не создаётся, служебное — создаётся (NTF-003 DoD)."""
    project = await _project(db_session, ProjectStatus.PREPARATION)
    moderator = await world.actor(SystemRole.MODERATOR)
    await _member(db_session, project, moderator.id, ProjectRole.MODERATOR)
    payload = {
        "project_id": str(project.id),
        "phase_id": str(uuid.uuid4()),
        "discipline_id": str(uuid.uuid4()),
        "actor_id": str(uuid.uuid4()),
    }
    assert (
        await inapp.notify(
            db_session,
            "branch_back_to_draft",
            [moderator.id],
            project_id=project.id,
            payload=payload,
        )
        == []
    )
    created = await inapp.notify(
        db_session,
        "member_blocked",
        [moderator.id],
        project_id=project.id,
        payload={"project_id": str(project.id), "blocked_user_id": str(uuid.uuid4())},
    )
    assert [n.kind for n in created] == ["member_blocked"]


@pytest.mark.parametrize(
    ("status", "kind", "allowed"),
    [
        ("preparation", "question_to_me", False),
        ("estimation", "question_to_me", True),
        ("consolidation", "moderator_change", True),
        ("completed", "question_to_me", False),
        ("completed", "answer_to_my_question", True),
        ("archived", "answer_to_my_question", False),
        ("archived", "member_blocked", True),
        ("archived", "support_session_opened", True),
    ],
)
def test_status_matrix(status: str, kind: str, allowed: bool) -> None:
    assert inapp.status_allows(kind, status) is allowed


def test_unknown_kind() -> None:
    with pytest.raises(inapp.UnknownKindError):
        inapp.status_allows("salary_raised", None)


async def test_recipient_rules(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    project = await _project(db_session, ProjectStatus.PREPARATION)
    author = await world.actor(SystemRole.MODERATOR)
    moderator = await world.actor(SystemRole.MODERATOR)
    blocked = await world.actor(SystemRole.MODERATOR)
    expert = await world.actor()
    stranger = await world.actor()
    for user, role in (
        (author, ProjectRole.MODERATOR),
        (moderator, ProjectRole.MODERATOR),
        (blocked, ProjectRole.MODERATOR),
        (expert, ProjectRole.EXPERT),
    ):
        await _member(db_session, project, user.id, role)
    row = await db_session.get(User, blocked.id)
    row.status, row.block_reason = UserStatus.BLOCKED, UserBlockReason.MANUAL
    await db_session.flush()
    payload = {"project_id": str(project.id), "actor_id": str(author.id)}
    created = await inapp.notify(
        db_session,
        "presale_head_joined",
        [author.id, moderator.id, blocked.id, expert.id, stranger.id],
        project_id=project.id,
        payload=payload,
        actor_id=author.id,
    )
    # автор — нет (N-AUTHOR), заблокированный — нет (N-BLOCKED), эксперт в «Подготовке» и
    # посторонний — нет (N-MEMBERSHIP)
    assert [n.user_id for n in created] == [moderator.id]
    await deliver_events(db_session)
    [event] = events.on(f"user:{moderator.id}")
    assert event["event"] == "notification.created"
    assert event["data"]["unread_count"] == 1
    assert event["data"]["notification"]["kind"] == "presale_head_joined"

    # «Проект без модератора» — всем администраторам, без членства в проекте
    admin = await world.actor(SystemRole.ADMIN)
    sent = await inapp.notify(
        db_session,
        "project_without_moderator",
        [admin.id],
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )
    assert [n.user_id for n in sent] == [admin.id]


async def test_list_and_read(world: World, db_session: AsyncSession) -> None:
    project = await _project(db_session, ProjectStatus.ESTIMATION)
    me = await world.actor()
    other = await world.actor()
    await _member(db_session, project, me.id, ProjectRole.EXPERT)
    await _member(db_session, project, other.id, ProjectRole.EXPERT)
    for _ in range(3):
        await inapp.notify(
            db_session,
            "moderator_change",
            [me.id, other.id],
            project_id=project.id,
            node_id=None,
            payload={"project_id": str(project.id), "fields": ["o"]},
        )
    first = await me.get("/notifications?limit=2")
    assert first.status_code == 200, first.text
    body = first.json()
    assert (len(body["items"]), body["unread"]) == (2, 3)
    assert body["next_cursor"]
    rest = (await me.get(f"/notifications?limit=2&cursor={body['next_cursor']}")).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None
    ids = [n["id"] for n in body["items"]]
    assert len({*ids, rest["items"][0]["id"]}) == 3

    foreign = (await other.get("/notifications")).json()["items"][0]["id"]
    read = await me.post("/notifications/read", json={"ids": [ids[0], foreign]})
    assert read.status_code == 204
    assert (await me.get("/notifications")).json()["unread"] == 2
    assert (await other.get("/notifications")).json()["unread"] == 3  # чужое не отмечено
    unread = (await me.get("/notifications?unread=true")).json()
    assert ids[0] not in [n["id"] for n in unread["items"]]
    assert await inapp.unread_by_project(db_session, me.id) == {project.id: 2}
    assert (await me.post("/notifications/read", json={"all": True})).status_code == 204
    after = (await me.get("/notifications")).json()
    assert after["unread"] == 0
    assert all(n["read_at"] for n in after["items"])
    bad = await me.get("/notifications?cursor=forged")
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")
