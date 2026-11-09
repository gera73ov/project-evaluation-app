"""CORE-011: жизненный цикл проекта — все разрешённые и запрещённые переходы, отмена с причиной,
предупреждения, даты, журнал, аудит, «Вас назначили» при запуске оценки (4.2, FR-PRJ-05,
BR-PRJ-01, BR-PRJ-03, BR-PRJ-04)."""

from __future__ import annotations

import itertools
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import BranchStatus, Project, ProjectMember
from estimator.db.models.tree import ProjectJournal
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.projects import lifecycle
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.helpers import audit_details, create_project, discipline

pytestmark = [pytest.mark.integration, pytest.mark.spec("4.2"), pytest.mark.spec("FR-PRJ-05")]

ALL = list(ProjectStatus)
CANCEL_REASON = "Заказчик отказался от проекта"


async def _set_status(db: AsyncSession, pid: uuid.UUID, status: ProjectStatus) -> None:
    await db.execute(update(Project).where(Project.id == pid).values(status=status))
    await db.flush()


async def _move(actor: Actor, pid: uuid.UUID, to: str, reason: str | None = None) -> object:
    body = {"to": to} | ({"reason": reason} if reason else {})
    return await actor.post(f"/projects/{pid}/status", json=body)


@pytest.mark.parametrize(("frm", "to"), list(itertools.product(ALL, ALL)))
async def test_transition_matrix(
    world: World, db_session: AsyncSession, frm: ProjectStatus, to: ProjectStatus
) -> None:
    """Каждая пара статусов: стрелка диаграммы — 200, иначе 409 ``INVALID_TRANSITION``."""
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await _set_status(db_session, pid, frm)
    reason = CANCEL_REASON if lifecycle.is_cancel(frm, to) else None
    response = await _move(moderator, pid, to.value, reason)
    if to in lifecycle.TRANSITIONS[frm]:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == to.value
        assert (await db_session.get(Project, pid, populate_existing=True)).status is to
    else:
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "INVALID_TRANSITION"
        assert (body["from"], body["to"]) == (frm.value, to.value)


@pytest.mark.spec("BR-PRJ-04")
async def test_cancel_requires_reason(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    await _set_status(db_session, pid, ProjectStatus.ESTIMATION)
    missing = await _move(moderator, pid, "archived")
    assert (missing.status_code, missing.json()["code"]) == (422, "VALIDATION_FAILED")
    short = await _move(moderator, pid, "archived", "мало")
    assert short.status_code == 422
    blank = await _move(moderator, pid, "archived", " " * 12)
    assert blank.status_code == 422

    done = await _move(moderator, pid, "archived", CANCEL_REASON)
    assert done.status_code == 200, done.text
    project = (await moderator.get(f"/projects/{pid}")).json()
    assert project["cancel_reason"] == CANCEL_REASON
    assert project["archived_at"]
    [entry] = [
        d
        for d in await audit_details(db_session, "project.status.changed", pid)
        if d["to"] == "archived"
    ]
    assert entry == entry | {
        "from": "estimation",
        "to": "archived",
        "automatic": False,
        "cancel_reason": CANCEL_REASON,
    }
    journal = (
        await db_session.scalars(
            select(ProjectJournal).where(
                ProjectJournal.project_id == pid, ProjectJournal.action == "project.status"
            )
        )
    ).one()
    assert journal.changes == {
        "status": ["estimation", "archived"],
        "cancel_reason": [None, CANCEL_REASON],
    }

    # «Восстановить»: в «Завершена», причина снята, срок автоархивации отсчитывается заново
    restored = await _move(moderator, pid, "completed")
    assert restored.status_code == 200
    project = (await moderator.get(f"/projects/{pid}")).json()
    assert (project["status"], project["cancel_reason"], project["archived_at"]) == (
        "completed",
        None,
        None,
    )
    assert project["completed_at"]


async def test_rights_and_events(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    expert = await world.actor()
    db_session.add(
        ProjectMember(
            project_id=pid,
            user_id=expert.id,
            role=ProjectRole.EXPERT,
            discipline_id=await discipline(db_session, "Бэкенд"),
        )
    )
    await db_session.flush()
    hidden = await _move(expert, pid, "estimation")  # в «Подготовке» эксперт проект не видит
    assert hidden.status_code == 404
    stranger = await world.actor(SystemRole.MODERATOR)
    assert (await _move(stranger, pid, "estimation")).status_code == 404

    before = (await db_session.get(Project, pid)).version
    response = await _move(moderator, pid, "estimation")
    assert response.json()["project_version"] == before + 1
    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{pid}") if e["event"] == "project.updated"]
    assert event["data"]["changes"] == {"status": "estimation"}
    assert event["project_version"] == before + 1
    denied = await _move(expert, pid, "consolidation")
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")


@pytest.mark.spec("BR-PRJ-01")
async def test_launch_notifies_and_warns(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    added = await moderator.post(
        f"/projects/{pid}/disciplines", json={"discipline_id": str(backend)}
    )
    assert added.status_code == 201, added.text
    added = await moderator.post(
        f"/projects/{pid}/disciplines",
        json={"discipline_id": str(await discipline(db_session, "QA"))},
    )
    assert added.status_code == 201
    expert = await world.actor()
    presale = await world.actor(SystemRole.PRESALE)
    team = {
        "members": [
            {"user_id": str(moderator.id), "role": "moderator"},
            {"user_id": str(expert.id), "role": "expert", "discipline_id": str(backend)},
            {
                "user_id": str(expert.id),
                "role": "expert",
                "discipline_id": str(backend),
                "is_reviewer": False,
            },
        ]
    }
    duplicated = await moderator.put(f"/projects/{pid}/members", json=team)
    assert (duplicated.status_code, duplicated.json()["code"]) == (409, "ALREADY_EXISTS")
    team["members"][2] = {"user_id": str(presale.id), "role": "presale"}
    assert (await moderator.put(f"/projects/{pid}/members", json=team)).status_code == 200

    async def notes(user_id: uuid.UUID) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.user_id == user_id, Notification.kind == "assigned_to_project"
        )
        return list((await db_session.scalars(stmt)).all())

    assert await notes(expert.id) == []  # в «Подготовке» — только при запуске (BR-PRJ-01)

    launched = await _move(moderator, pid, "estimation")
    assert launched.status_code == 200
    assert launched.json()["warnings"] == [{"code": "disciplines_without_expert", "count": 1}]
    [note] = await notes(expert.id)
    assert note.payload == {
        "project_id": str(pid),
        "actor_id": str(moderator.id),
        "roles": ["expert"],
        "discipline_ids": [str(backend)],
    }
    assert [n.payload["roles"] for n in await notes(presale.id)] == [["presale"]]
    rows = (
        await db_session.scalars(select(ProjectMember).where(ProjectMember.project_id == pid))
    ).all()
    assert all(r.notified_at for r in rows if r.role is not ProjectRole.MODERATOR)

    # «Перейти к сведению»: ветки «черновик» и «не начато» — предупреждение
    to_consolidation = await _move(moderator, pid, "consolidation")
    assert to_consolidation.json()["warnings"] == [{"code": "branches_not_done", "count": 4}]
    assert not await lifecycle.all_branches_ready(db_session, pid)
    await db_session.execute(
        update(BranchStatus)
        .where(BranchStatus.project_id == pid)
        .values(status=BranchStatusValue.DONE)
    )
    assert await lifecycle.all_branches_ready(db_session, pid)
    completed = await _move(moderator, pid, "completed")
    assert completed.json()["warnings"] == [{"code": "no_snapshot", "count": 1}]
    # переоткрытие и повторный запуск не шлют «Вас назначили» ещё раз
    assert (await _move(moderator, pid, "estimation")).status_code == 200
    assert len(await notes(expert.id)) == 1
