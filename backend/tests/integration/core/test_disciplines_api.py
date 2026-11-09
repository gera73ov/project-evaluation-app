"""CORE-013: дисциплины проекта — «Добавить дисциплину» (ветки во всех включённых фазах, «не
начато», профиль по умолчанию), удаление только пустой (409), смена профиля ветки экспертом своей
дисциплины и модератором (FR-PRJ-04, 5.1, FR-TREE-04, 4.3)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, NodeKind, ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.dictionaries import Discipline, DisciplineProfile
from estimator.db.models.projects import BranchStatus, Project, ProjectMember
from estimator.db.models.tree import Node, ProjectJournal
from estimator.db.uuid7 import uuid7
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.tree import load
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.helpers import create_project, discipline

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PRJ-04")]


async def test_add_discipline(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator, "Разработка", "Тестирование", "Внедрение")
    backend = await discipline(db_session, "Бэкенд")
    url = f"/projects/{pid}/disciplines"
    response = await moderator.post(url, json={"discipline_id": str(backend)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["nodes"]) == 3  # три фазы работ, без «Управления проектом»
    assert {n["kind"] for n in body["nodes"]} == {"discipline"}
    assert {n["title"] for n in body["nodes"]} == {"Бэкенд"}
    assert {b["status"] for b in body["branch_statuses"]} == {"not_started"}
    assert body["totals"] == {"e": "0.00", "sigma": "0.00", "p80": "0.00", "p90": "0.00"}
    statuses = (
        await db_session.scalars(select(BranchStatus.status).where(BranchStatus.project_id == pid))
    ).all()
    assert list(statuses) == [BranchStatusValue.NOT_STARTED] * 3
    project = (await moderator.get(f"/projects/{pid}")).json()
    [row] = project["disciplines"]
    default = (await db_session.get(Discipline, backend)).default_profile_id
    assert row == {
        "discipline_id": str(backend),
        "name": "Бэкенд",
        "profile_id": str(default),
        "has_expert": False,
    }
    assert project["version"] == body["project_version"]
    await deliver_events(db_session)
    names = [e["event"] for e in events.on(f"project:{pid}")]
    assert names == ["node.created"] * 3 + ["project.updated"]

    again = await moderator.post(url, json={"discipline_id": str(backend)})
    assert (again.status_code, again.json()["code"]) == (409, "ALREADY_EXISTS")
    missing = await moderator.post(url, json={"discipline_id": str(uuid7())})
    assert missing.status_code == 422

    expert = await world.actor()
    db_session.add(
        ProjectMember(
            project_id=pid, user_id=expert.id, role=ProjectRole.EXPERT, discipline_id=backend
        )
    )
    await db_session.execute(
        update(Project).where(Project.id == pid).values(status=ProjectStatus.ESTIMATION)
    )
    denied = await expert.post(url, json={"discipline_id": str(await discipline(db_session, "QA"))})
    assert denied.status_code == 403


@pytest.mark.spec("BR-TREE-06")
async def test_add_discipline_nodes_limit(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    from estimator.services.projects import disciplines

    monkeypatch.setattr(
        disciplines, "NODES_LIMIT", await load.count_live_nodes(db_session, pid) + 1
    )
    response = await moderator.post(
        f"/projects/{pid}/disciplines",
        json={"discipline_id": str(await discipline(db_session, "Бэкенд"))},
    )
    assert (response.status_code, response.json()["code"]) == (409, "NODES_LIMIT")
    assert response.json()["requested"] == 2


@pytest.mark.spec("5.1")
async def test_remove_discipline(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    qa = await discipline(db_session, "QA")
    for d in (backend, qa):
        assert (
            await moderator.post(f"/projects/{pid}/disciplines", json={"discipline_id": str(d)})
        ).status_code == 201
    expert = await world.actor()
    await moderator.put(
        f"/projects/{pid}/members",
        json={
            "members": [
                {"user_id": str(moderator.id), "role": "moderator"},
                {"user_id": str(expert.id), "role": "expert", "discipline_id": str(qa)},
            ]
        },
    )
    branch = (
        await db_session.scalars(
            select(Node).where(
                Node.project_id == pid,
                Node.discipline_id == backend,
                Node.kind == NodeKind.DISCIPLINE,
            )
        )
    ).first()
    db_session.add(
        Node(
            id=uuid7(),
            project_id=pid,
            parent_id=branch.id,
            kind=NodeKind.ITEM,
            phase_id=branch.phase_id,
            discipline_id=backend,
            title="Личный кабинет",
            position="a0",
        )
    )
    await db_session.flush()
    busy = await moderator.delete(f"/projects/{pid}/disciplines/{backend}")
    assert (busy.status_code, busy.json()["code"]) == (409, "BRANCH_NOT_EMPTY")

    assert (await moderator.delete(f"/projects/{pid}/disciplines/{qa}")).status_code == 204
    project = (await moderator.get(f"/projects/{pid}")).json()
    assert [d["discipline_id"] for d in project["disciplines"]] == [str(backend)]
    live = (
        await db_session.scalars(
            select(Node.id).where(
                Node.project_id == pid, Node.discipline_id == qa, Node.deleted_at.is_(None)
            )
        )
    ).all()
    assert live == []
    members = (await moderator.get(f"/projects/{pid}/members")).json()["items"]
    assert [m["user"]["id"] for m in members] == [str(moderator.id)]  # эксперт QA снят
    gone = await moderator.delete(f"/projects/{pid}/disciplines/{qa}")
    assert gone.status_code == 404


@pytest.mark.spec("FR-TREE-04")
async def test_branch_profile(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await create_project(world, moderator)
    backend = await discipline(db_session, "Бэкенд")
    qa = await discipline(db_session, "QA")
    for d in (backend, qa):
        await moderator.post(f"/projects/{pid}/disciplines", json={"discipline_id": str(d)})
    expert = await world.actor()
    await moderator.put(
        f"/projects/{pid}/members",
        json={
            "members": [
                {"user_id": str(moderator.id), "role": "moderator"},
                {"user_id": str(expert.id), "role": "expert", "discipline_id": str(backend)},
            ]
        },
    )
    await moderator.post(f"/projects/{pid}/status", json={"to": "estimation"})
    await db_session.execute(
        update(BranchStatus)
        .where(BranchStatus.project_id == pid)
        .values(status=BranchStatusValue.DONE)
    )
    profiles = {
        p.name: p.id
        for p in (
            await db_session.scalars(
                select(DisciplineProfile).where(DisciplineProfile.discipline_id == backend)
            )
        ).all()
    }
    url = f"/projects/{pid}/disciplines/{backend}"
    response = await expert.patch(url, json={"profile_id": str(profiles["Сервис → Функция"])})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "discipline_id": str(backend),
        "name": "Бэкенд",
        "profile_id": str(profiles["Сервис → Функция"]),
        "has_expert": True,
    }
    # «готово» не сбрасывается, смена — в журнале проекта
    statuses = set(
        (
            await db_session.scalars(
                select(BranchStatus.status).where(BranchStatus.project_id == pid)
            )
        ).all()
    )
    assert statuses == {BranchStatusValue.DONE}
    journal = (
        await db_session.scalars(
            select(ProjectJournal.changes).where(
                ProjectJournal.project_id == pid, ProjectJournal.action == "project.branch_profile"
            )
        )
    ).one()
    assert journal["profile"] == ["Модуль → Функция", "Сервис → Функция"]

    qa_profile = (
        await db_session.scalars(
            select(DisciplineProfile.id).where(DisciplineProfile.discipline_id == qa)
        )
    ).first()
    foreign = await expert.patch(
        f"/projects/{pid}/disciplines/{qa}", json={"profile_id": str(qa_profile)}
    )
    assert foreign.status_code == 403  # эксперт — только своя дисциплина
    assert (
        await moderator.patch(
            f"/projects/{pid}/disciplines/{qa}", json={"profile_id": str(qa_profile)}
        )
    ).status_code == 200
    wrong = await moderator.patch(url, json={"profile_id": str(qa_profile)})
    assert (wrong.status_code, wrong.json()["code"]) == (422, "VALIDATION_FAILED")
