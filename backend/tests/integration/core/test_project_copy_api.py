"""CORE-023: копирование проекта (FR-PRJ-02) — копия в «Подготовке» с настройками, командой и
деревом, без обсуждений, истории и «Проверено»; ставки — только у модератора источника; эксперт и
пресейл копировать не могут."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, NodeKind, SystemRole
from estimator.db.models.money import ProjectRate
from estimator.db.models.projects import BranchStatus, Project, ProjectMember
from estimator.db.models.tree import Node, NodeHistory
from estimator.db.models.users import UserRole
from estimator.db.uuid7 import uuid7
from estimator.services.projects.copy import copy_name
from tests.integration.core.conftest import World
from tests.integration.core.test_review_api import _review, _with_reviewer
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-PRJ-02")]


async def test_copy_project(world: World, db_session: AsyncSession) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    branch = await s.branch(db_session, s.backend)
    group = await _leaf(s.backend_expert, s, branch.id, "Модуль")
    await _leaf(s.backend_expert, s, group["id"], "Вход", o="8", r="12", p="20")
    gone = await _leaf(s.backend_expert, s, branch.id, "В корзине")
    await s.backend_expert.delete(f"/nodes/{gone['id']}")
    local = await s.backend_expert.post(
        f"/projects/{s.pid}/node-types", json={"name": "Отчёт", "icon": "report"}
    )
    assert local.status_code == 201, local.text
    await _leaf(s.backend_expert, s, group["id"], "Сводка", type_id=local.json()["id"])
    await _review(reviewer, branch.id)
    db_session.add(
        ProjectRate(
            id=uuid7(),
            project_id=s.pid,
            discipline_id=s.backend,
            rate_rub=Decimal(3000),
            created_by=s.moderator.id,
            updated_by=s.moderator.id,
        )
    )
    await db_session.flush()

    # эксперт копировать не может
    assert (await s.backend_expert.post(f"/projects/{s.pid}/copy", json={})).status_code == 403

    copied = await s.moderator.post(f"/projects/{s.pid}/copy", json={})
    assert copied.status_code == 201, copied.text
    body = copied.json()["project"]
    new_id = uuid.UUID(body["id"])
    source = await db_session.get(Project, s.pid)
    assert (body["name"], body["status"]) == (copy_name(source.name), "preparation")
    target = await db_session.get(Project, new_id)
    assert target.copied_from_id == s.pid

    async def live(pid: uuid.UUID) -> list[Node]:
        return list(
            (
                await db_session.scalars(
                    select(Node).where(Node.project_id == pid, Node.deleted_at.is_(None))
                )
            ).all()
        )

    old_nodes, new_nodes = await live(s.pid), await live(new_id)
    assert sorted(n.title for n in new_nodes) == sorted(n.title for n in old_nodes)
    assert "В корзине" not in {n.title for n in new_nodes}
    assert all(n.reviewed_by is None for n in new_nodes)
    by_title = {n.title: n for n in new_nodes}
    assert (by_title["Вход"].o, by_title["Вход"].p) == (Decimal(8), Decimal(20))
    assert by_title["Вход"].parent_id == by_title["Модуль"].id
    summary_type = by_title["Сводка"].type_id
    assert summary_type is not None
    assert summary_type != uuid.UUID(local.json()["id"])  # локальный тип скопирован в проект
    history = await db_session.scalar(select(func.count()).where(NodeHistory.project_id == new_id))
    assert history == 0

    statuses = {
        (r.phase_id, r.discipline_id): r.status
        for r in (
            await db_session.scalars(select(BranchStatus).where(BranchStatus.project_id == new_id))
        ).all()
    }
    assert statuses[(branch.phase_id, s.backend)] is BranchStatusValue.DRAFT
    assert BranchStatusValue.DONE not in statuses.values()

    team = {
        (m.user_id, m.role, m.discipline_id, m.is_reviewer)
        for m in (
            await db_session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == new_id)
            )
        ).all()
    }
    assert (reviewer.id, "expert", s.backend, True) in {(u, str(r), d, rv) for u, r, d, rv in team}
    assert len(team) == 4
    rates = (
        await db_session.scalars(
            select(ProjectRate.rate_rub).where(ProjectRate.project_id == new_id)
        )
    ).all()
    assert list(rates) == [Decimal(3000)]

    named = await s.moderator.post(f"/projects/{s.pid}/copy", json={"name": "  Новый портал "})
    assert named.json()["project"]["name"] == "Новый портал"
    phases = [n for n in new_nodes if n.kind is NodeKind.PHASE]
    assert phases


async def test_copy_requires_system_moderator(world: World, db_session: AsyncSession) -> None:
    """Модератор проекта без системной роли «Модератор» и пресейл копировать не могут."""
    s, _ = await _with_reviewer(world, db_session)
    plain = await world.actor(SystemRole.MODERATOR)
    presale = await world.actor(SystemRole.PRESALE)
    team = await s.moderator.get(f"/projects/{s.pid}/members")
    members = [
        {k: v for k, v in m.items() if k in ("role", "discipline_id", "is_reviewer")}
        | {"user_id": m["user"]["id"]}
        for m in team.json()["items"]
    ]
    members += [
        {"user_id": str(plain.id), "role": "moderator"},
        {"user_id": str(presale.id), "role": "presale"},
    ]
    put = await s.moderator.put(f"/projects/{s.pid}/members", json={"members": members})
    assert put.status_code == 200, put.text
    # системную роль «Модератор» сняли: модератором проекта он остаётся, копировать — нет
    await db_session.execute(
        delete(UserRole).where(UserRole.user_id == plain.id, UserRole.role == SystemRole.MODERATOR)
    )
    plain = await world.session_for(plain.id)
    assert (await plain.post(f"/projects/{s.pid}/copy", json={})).status_code == 403
    assert (await presale.post(f"/projects/{s.pid}/copy", json={})).status_code == 403
    assert len(copy_name("Я" * 200)) == 200
