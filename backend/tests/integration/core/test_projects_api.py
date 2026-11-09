"""CORE-010: создание проекта, значения по умолчанию, узлы фаз, PATCH настроек и выключение фаз.

SPEC FR-PRJ-01, FR-PRJ-05 «Создание», FR-HOME-03, 5.1, BR-CALC-05, BR-MONEY-05/06, C-31, 15.2.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeKind, ProjectRole, SystemRole
from estimator.db.models.dictionaries import Discipline, DisciplineProfile
from estimator.db.models.projects import (
    BranchStatus,
    ProjectDiscipline,
    ProjectMember,
)
from estimator.db.models.tree import ChangeLog, Node, ProjectJournal
from estimator.db.uuid7 import uuid7
from estimator.realtime.bus.memory import InMemoryBus
from tests.helpers.money_keys import assert_no_money
from tests.integration.core.conftest import Actor, World, deliver_events

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PRJ-01"), pytest.mark.spec("15.2")]


async def _create(actor: Actor, phases: list[uuid.UUID], **extra: Any) -> dict[str, Any]:
    body = {
        "name": "Портал дилеров",
        "customer": "ООО Ромашка",
        "phase_ids": [str(p) for p in phases],
    }
    response = await actor.post("/projects", json=body | extra)
    assert response.status_code == 201, response.text
    return response.json()


async def _audit(db: AsyncSession, event: str, project_id: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e AND object_id = :o"),
        {"e": event, "o": project_id},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.spec("FR-PRJ-05")
@pytest.mark.spec("BR-CALC-05")
@pytest.mark.spec("BR-MONEY-06")
async def test_create_with_defaults(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    created = await _create(moderator, [phases["Разработка"], phases["Гарантийная поддержка"]])
    project = created["project"]
    assert created["project_version"] == project["version"] == 1
    assert project["status"] == "preparation"
    assert project["detail_level"] == "medium"
    assert project["quote_figure"] == "p80"
    assert project["pm_percent"] == "18"
    assert project["access"] == "member"
    assert {"project.settings.write", "tree.read", "money.read"} <= set(project["my_permissions"])
    by_name = {p["name"]: p for p in project["phases"]}
    assert len(by_name) == len(phases)
    assert by_name["Разработка"]["is_enabled"]
    assert by_name["Разработка"]["in_pm_base"]
    assert by_name["Гарантийная поддержка"]["is_enabled"]
    assert not by_name["Гарантийная поддержка"]["in_pm_base"]
    assert not by_name["Тестирование"]["is_enabled"]
    pm = by_name["Управление проектом"]
    assert pm["is_cross_cutting"]
    assert pm["is_enabled"]
    assert not pm["in_pm_base"]

    pid = uuid.UUID(project["id"])
    member = (
        await db_session.scalars(select(ProjectMember).where(ProjectMember.project_id == pid))
    ).one()
    assert (member.user_id, member.role) == (moderator.id, ProjectRole.MODERATOR)
    nodes = (await db_session.scalars(select(Node).where(Node.project_id == pid))).all()
    assert {n.title for n in nodes} == {
        "Разработка",
        "Гарантийная поддержка",
        "Управление проектом",
    }
    assert all(n.kind is NodeKind.PHASE for n in nodes)
    money = (
        await db_session.execute(
            text(
                "SELECT currency, exchange_rate, vat_percent FROM project_money "
                "WHERE project_id = :p"
            ),
            {"p": pid},
        )
    ).one()
    assert (money[0], str(money[1]), str(money[2])) == ("RUB", "1.0000", "22.00")  # C-31
    assert await _audit(db_session, "project.created", project["id"]) == [
        {"copied_from": None, "rates_copied": False, "project_id": project["id"]}
    ]
    journal = (
        await db_session.scalars(
            select(ProjectJournal.action).where(ProjectJournal.project_id == pid)
        )
    ).all()
    assert journal == ["project.created"]


@pytest.mark.spec("7.5")
async def test_pm_percent_from_settings(world: World) -> None:
    from tests.integration.auth.conftest import set_setting

    await set_setting(world.db, "method.pm_percent_default", 12.5)
    moderator = await world.actor(SystemRole.MODERATOR)
    created = await _create(moderator, [(await world.phases())["Разработка"]])
    assert created["project"]["pm_percent"] == "12.5"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"name": "ab"}, "VALIDATION_FAILED"),
        ({"name": "x" * 201}, "VALIDATION_FAILED"),
        ({"customer": ""}, "VALIDATION_FAILED"),
        ({"description": "x" * 10001}, "VALIDATION_FAILED"),
        ({"phase_ids": []}, "VALIDATION_FAILED"),
        ({"phase_ids": [str(uuid.uuid4())]}, "VALIDATION_FAILED"),
        ({"detail_level": "huge"}, "VALIDATION_FAILED"),
        ({"deadline": "2000-01-01"}, "VALUE_OUT_OF_RANGE"),
        ({"money": "1"}, "VALIDATION_FAILED"),
    ],
)
async def test_create_validation(world: World, body: dict[str, Any], code: str) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    base = {"name": "Портал", "customer": "ООО", "phase_ids": [str(phases["Разработка"])]}
    response = await moderator.post("/projects", json=base | body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code


async def test_only_pm_phase_is_not_enough(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    response = await moderator.post(
        "/projects",
        json={
            "name": "Портал",
            "customer": "ООО",
            "phase_ids": [str(phases["Управление проектом"])],
        },
    )
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_FAILED")


async def test_deadline_today_is_allowed(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    today = (
        dt.datetime.now(dt.UTC).astimezone(__import__("zoneinfo").ZoneInfo("Europe/Moscow")).date()
    )
    created = await _create(
        moderator, [(await world.phases())["Разработка"]], deadline=today.isoformat()
    )
    assert created["project"]["deadline"] == today.isoformat()


@pytest.mark.spec("3.3")
async def test_create_needs_moderator_role(world: World) -> None:
    for roles in ((), (SystemRole.PRESALE,), (SystemRole.ADMIN,)):
        actor = await world.actor(*roles)
        response = await actor.post(
            "/projects",
            json={"name": "Портал", "customer": "ООО", "phase_ids": [str(uuid.uuid4())]},
        )
        assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")


@pytest.mark.spec("Q-25")
async def test_admin_moderator_creator_marked(world: World, db_session: AsyncSession) -> None:
    actor = await world.actor(SystemRole.MODERATOR, SystemRole.ADMIN)
    created = await _create(actor, [(await world.phases())["Разработка"]])
    member = (
        await db_session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == uuid.UUID(created["project"]["id"])
            )
        )
    ).one()
    assert member.added_by_admin_self


async def test_get_project_visibility(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = (await _create(moderator, [(await world.phases())["Разработка"]]))["project"]["id"]
    got = await moderator.get(f"/projects/{pid}")
    assert got.status_code == 200
    assert got.json()["name"] == "Портал дилеров"
    assert_no_money(got.json())

    stranger = await world.actor(SystemRole.MODERATOR)
    assert (await stranger.get(f"/projects/{pid}")).status_code == 404
    # эксперт в «Подготовке» проект не видит (M3.4-01)
    expert = await world.actor()
    discipline = (
        await db_session.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))
    ).one()
    db_session.add(
        ProjectMember(
            project_id=uuid.UUID(pid),
            user_id=expert.id,
            role=ProjectRole.EXPERT,
            discipline_id=discipline,
        )
    )
    await db_session.flush()
    assert (await expert.get(f"/projects/{pid}")).status_code == 404
    head = await world.actor(SystemRole.PRESALE_HEAD)
    seen = await head.get(f"/projects/{pid}")
    assert seen.status_code == 200
    assert seen.json()["access"] == "presale_head"


@pytest.mark.spec("BR-PRJ-06")
async def test_patch_settings(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    project = (await _create(moderator, [(await world.phases())["Разработка"]]))["project"]
    pid = project["id"]
    response = await moderator.patch(
        f"/projects/{pid}",
        json={
            "pm_percent": "12,5",
            "pm_percent_reason": "Небольшая команда",
            "quote_figure": "p90",
            "duration_weeks": 12,
            "name": "  Портал дилеров 2  ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_version"] == 2
    assert body["project"]["pm_percent"] == "12.5"
    assert body["project"]["name"] == "Портал дилеров 2"
    assert (body["project"]["quote_figure"], body["project"]["duration_weeks"]) == ("p90", 12)
    await deliver_events(db_session)
    [event] = events.on(f"project:{pid}")
    assert event["event"] == "project.updated"
    assert event["project_version"] == 2
    assert event["data"]["changes"]["pm_percent"] == "12.5"
    assert event["data"]["author"]["id"] == str(moderator.id)
    log = (
        await db_session.scalars(select(ChangeLog).where(ChangeLog.project_id == uuid.UUID(pid)))
    ).all()
    assert [c.version for c in log] == [2]
    journal = (
        await db_session.scalars(
            select(ProjectJournal).where(
                ProjectJournal.project_id == uuid.UUID(pid),
                ProjectJournal.action == "project.settings",
            )
        )
    ).one()
    assert journal.changes["pm_percent"] == ["18", "12.5"]
    assert journal.changes["duration_weeks"] == [None, 12]

    # без изменений версия не растёт и событий нет
    again = await moderator.patch(f"/projects/{pid}", json={"quote_figure": "p90"})
    assert again.json()["project_version"] == 2
    assert len(events.on(f"project:{pid}")) == 1


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"pm_percent": "50.5"}, 422, "VALUE_OUT_OF_RANGE"),
        ({"pm_percent": "-1"}, 422, "VALUE_OUT_OF_RANGE"),
        ({"pm_percent": "10.3"}, 422, "VALUE_OUT_OF_RANGE"),
        ({"pm_percent": 10}, 422, "VALIDATION_FAILED"),
        ({"duration_weeks": 261}, 422, "VALIDATION_FAILED"),
        ({"pm_percent_reason": "x" * 1001}, 422, "VALIDATION_FAILED"),
        ({"deadline": "2001-01-01"}, 422, "VALUE_OUT_OF_RANGE"),
        ({"name": "  a  "}, 422, "VALIDATION_FAILED"),
    ],
)
async def test_patch_validation(world: World, body: dict[str, Any], status: int, code: str) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = (await _create(moderator, [(await world.phases())["Разработка"]]))["project"]["id"]
    response = await moderator.patch(f"/projects/{pid}", json=body)
    assert (response.status_code, response.json()["code"]) == (status, code), response.text


async def test_expert_cannot_patch(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = (await _create(moderator, [(await world.phases())["Разработка"]]))["project"]["id"]
    await db_session.execute(
        text("UPDATE projects SET status = 'estimation' WHERE id = :p"), {"p": pid}
    )
    expert = await world.actor()
    discipline = (
        await db_session.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))
    ).one()
    db_session.add(
        ProjectMember(
            project_id=uuid.UUID(pid),
            user_id=expert.id,
            role=ProjectRole.EXPERT,
            discipline_id=discipline,
        )
    )
    await db_session.flush()
    assert (await expert.get(f"/projects/{pid}")).status_code == 200
    response = await expert.patch(f"/projects/{pid}", json={"pm_percent": "10"})
    assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")


@pytest.mark.spec("5.1")
async def test_pm_phase_cannot_be_disabled(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    pid = (await _create(moderator, [phases["Разработка"]]))["project"]["id"]
    response = await moderator.patch(
        f"/projects/{pid}",
        json={"phases": [{"phase_id": str(phases["Управление проектом"]), "is_enabled": False}]},
    )
    assert (response.status_code, response.json()["code"]) == (409, "CROSS_CUTTING_PHASE_LOCKED")


async def _add_discipline(db: AsyncSession, pid: uuid.UUID, phase_id: uuid.UUID, name: str) -> Node:
    """Ветка дисциплины в фазе (до CORE-013 — напрямую в БД)."""
    discipline = (await db.scalars(select(Discipline).where(Discipline.name == name))).one()
    profile = (
        await db.scalars(
            select(DisciplineProfile.id).where(DisciplineProfile.discipline_id == discipline.id)
        )
    ).first()
    db.add(ProjectDiscipline(project_id=pid, discipline_id=discipline.id, profile_id=profile))
    phase_node = (
        await db.scalars(
            select(Node).where(
                Node.project_id == pid, Node.phase_id == phase_id, Node.kind == NodeKind.PHASE
            )
        )
    ).one()
    branch = Node(
        id=uuid7(),
        project_id=pid,
        parent_id=phase_node.id,
        kind=NodeKind.DISCIPLINE,
        phase_id=phase_id,
        discipline_id=discipline.id,
        title=name,
        position="a0",
    )
    db.add(branch)
    db.add(BranchStatus(project_id=pid, phase_id=phase_id, discipline_id=discipline.id))
    await db.flush()
    return branch


@pytest.mark.spec("11.6")
async def test_disable_phase_with_branches(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    dev, test = phases["Разработка"], phases["Тестирование"]
    pid = uuid.UUID((await _create(moderator, [dev, test]))["project"]["id"])
    branch = await _add_discipline(db_session, pid, test, "Бэкенд")

    # пустая ветка — без подтверждения
    off = {"phases": [{"phase_id": str(test), "is_enabled": False}]}
    response = await moderator.patch(f"/projects/{pid}", json=off)
    assert response.status_code == 200, response.text
    await db_session.refresh(branch)
    assert branch.deleted_at is not None

    on = {"phases": [{"phase_id": str(test), "is_enabled": True}]}
    assert (await moderator.patch(f"/projects/{pid}", json=on)).status_code == 200
    fresh = (
        await db_session.scalars(
            select(Node).where(
                Node.project_id == pid,
                Node.phase_id == test,
                Node.kind == NodeKind.DISCIPLINE,
                Node.deleted_at.is_(None),
            )
        )
    ).one()
    db_session.add(
        Node(
            id=uuid7(),
            project_id=pid,
            parent_id=fresh.id,
            kind=NodeKind.ITEM,
            phase_id=test,
            discipline_id=fresh.discipline_id,
            title="Регресс",
            position="a0",
        )
    )
    await db_session.flush()

    need = await moderator.patch(f"/projects/{pid}", json=off)
    assert need.status_code == 409
    assert need.json()["code"] == "CONFIRMATION_REQUIRED"
    assert need.json()["consequence"] == "branches_to_trash"
    assert need.json()["affected"] == 1
    done = await moderator.patch(f"/projects/{pid}", json=off | {"confirm": True})
    assert done.status_code == 200
    test_phase = next(p for p in done.json()["project"]["phases"] if p["phase_id"] == str(test))
    assert not test_phase["is_enabled"]
    live = await db_session.scalar(
        select(func.count()).where(
            Node.project_id == pid,
            Node.phase_id == test,
            Node.kind != NodeKind.PHASE,
            Node.deleted_at.is_(None),
        )
    )
    assert live == 0
    batches = await db_session.scalar(
        select(func.count(func.distinct(Node.deleted_batch_id))).where(
            Node.project_id == pid, Node.id != branch.id, Node.deleted_at.is_not(None)
        )
    )
    assert batches == 1  # ветка с ребёнком — одним пакетом


async def test_last_work_phase_stays(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    pid = (await _create(moderator, [phases["Разработка"]]))["project"]["id"]
    response = await moderator.patch(
        f"/projects/{pid}",
        json={"phases": [{"phase_id": str(phases["Разработка"]), "is_enabled": False}]},
    )
    assert (response.status_code, response.json()["code"]) == (422, "VALIDATION_FAILED")


@pytest.mark.spec("BR-CALC-05")
async def test_pm_base_flags(world: World, events: InMemoryBus, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    dev = phases["Разработка"]
    pid = (await _create(moderator, [dev]))["project"]["id"]
    response = await moderator.patch(
        f"/projects/{pid}", json={"phases": [{"phase_id": str(dev), "in_pm_base": False}]}
    )
    assert response.status_code == 200
    phase = next(p for p in response.json()["project"]["phases"] if p["phase_id"] == str(dev))
    assert not phase["in_pm_base"]
    await deliver_events(db_session)
    [event] = events.on(f"project:{pid}")
    assert str(dev) not in event["data"]["changes"]["pm_base_phase_ids"]


async def test_enable_new_phase_creates_nodes(world: World, db_session: AsyncSession) -> None:
    """Фаза, не выбранная при создании: включение даёт узел-фазу и ветки дисциплин проекта."""
    moderator = await world.actor(SystemRole.MODERATOR)
    phases = await world.phases()
    dev, test = phases["Разработка"], phases["Тестирование"]
    pid = uuid.UUID((await _create(moderator, [dev]))["project"]["id"])
    await _add_discipline(db_session, pid, dev, "Бэкенд")
    on = {"phases": [{"phase_id": str(test), "is_enabled": True}]}
    response = await moderator.patch(f"/projects/{pid}", json=on)
    assert response.status_code == 200, response.text
    nodes = (
        await db_session.scalars(select(Node).where(Node.project_id == pid, Node.phase_id == test))
    ).all()
    assert sorted(str(n.kind) for n in nodes) == ["discipline", "phase"]
    status = await db_session.get(
        BranchStatus, (pid, test, nodes[0].discipline_id or nodes[1].discipline_id)
    )
    assert status is not None
    assert str(status.status) == "not_started"
    tree = (await moderator.get(f"/projects/{pid}/tree")).json()
    titles = [n["title"] for n in tree["nodes"] if n["parent_id"] is None]
    assert titles == ["Разработка", "Тестирование", "Управление проектом"]
