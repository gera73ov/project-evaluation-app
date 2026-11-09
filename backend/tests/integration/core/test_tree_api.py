"""CORE-014: дерево целиком с расчётом при выдаче; суммы совпадают с эталоном CORE-007.

SPEC 5.1, 14.3, ARCH-03, BR-TREE-01, BR-TREE-06, NFR-LIM-01, 15.2 ``GET /projects/{id}/tree``.
"""

from __future__ import annotations

import sys
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeKind, ProjectRole, SystemRole
from estimator.db.models.dictionaries import Discipline, DisciplineProfile
from estimator.db.models.projects import BranchStatus, Project, ProjectDiscipline, ProjectMember
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.services.tree.load import load_tree
from estimator.services.tree.positions import keys_after
from tests.factories.projects import _calc_fixture
from tests.helpers.money_keys import assert_no_money
from tests.integration.core.conftest import Actor, World

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.3"), pytest.mark.spec("ARCH-03")]


def _close(actual: str, expected: str) -> bool:
    """Правило фикстур: ROUND_HALF_UP до числа знаков ожидаемой строки."""
    places = len(expected.split(".")[1]) if "." in expected else 0
    quant = Decimal(1).scaleb(-places)
    return Decimal(actual).quantize(quant, rounding=ROUND_HALF_UP) == Decimal(expected)


async def _portal(world: World, moderator: Actor) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """«Портал дилеров» из фикстуры CORE-001: проект через API, ветки и листья — в БД."""
    data = _calc_fixture()["input"]
    phases = await world.phases()
    fixture_phase = {p["id"]: phases[p["name"]] for p in data["phases"]}
    work = [fixture_phase[p["id"]] for p in data["phases"] if not p["is_cross_cutting"]]
    response = await moderator.post(
        "/projects",
        json={"name": "Портал дилеров", "customer": "ООО", "phase_ids": [str(p) for p in work]},
    )
    assert response.status_code == 201, response.text
    pid = uuid.UUID(response.json()["project"]["id"])
    db = world.db
    # база УП в эталоне — все три фазы работ
    await db.execute(
        text(
            "UPDATE project_phases SET in_pm_base = true WHERE project_id = :p "
            "AND phase_id = ANY(:ids)"
        ),
        {"p": pid, "ids": work},
    )
    disciplines: dict[str, uuid.UUID] = {}
    for d in data["disciplines"]:
        did = (await db.scalars(select(Discipline.id).where(Discipline.name == d["name"]))).one()
        profile = (
            await db.scalars(
                select(DisciplineProfile.id).where(DisciplineProfile.discipline_id == did)
            )
        ).first()
        db.add(ProjectDiscipline(project_id=pid, discipline_id=did, profile_id=profile))
        disciplines[d["id"]] = did
    phase_nodes = {
        n.phase_id: n.id
        for n in (await db.scalars(select(Node).where(Node.project_id == pid))).all()
    }
    ids: dict[str, uuid.UUID] = {}
    positions = iter(keys_after(None, len(data["nodes"])))
    for n in data["nodes"]:
        phase_id = fixture_phase[n["phase_id"]]
        if n["kind"] == "phase":
            ids[n["id"]] = phase_nodes[phase_id]
            continue
        node_id = uuid7()
        ids[n["id"]] = node_id
        discipline = disciplines[n["discipline_id"]]
        db.add(
            Node(
                id=node_id,
                project_id=pid,
                parent_id=ids[n["parent_id"]],
                kind=NodeKind(n["kind"]),
                phase_id=phase_id,
                discipline_id=discipline,
                title=n["title"],
                position=next(positions),
                o=Decimal(n["o"]) if n.get("o") is not None else None,
                r=Decimal(n["r"]) if n.get("r") is not None else None,
                p=Decimal(n["p"]) if n.get("p") is not None else None,
                multiplier=n.get("multiplier", 1),
            )
        )
        if n["kind"] == "discipline":
            db.add(BranchStatus(project_id=pid, phase_id=phase_id, discipline_id=discipline))
        await db.flush()
    return pid, ids


@pytest.mark.tc("TC-CALC-01")
async def test_tree_matches_reference(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid, ids = await _portal(world, moderator)
    response = await moderator.get(f"/projects/{pid}/tree")
    assert response.status_code == 200, response.text
    tree = response.json()
    assert_no_money(tree)
    expected = _calc_fixture()["expected"]
    by_id = {n["id"]: n for n in tree["nodes"]}
    for key, values in expected["leaves"]["values"].items():
        node = by_id[str(ids[key])]
        assert node["leaf_state"] == "valid"
        for field in ("e", "sigma", "p80", "p90"):
            assert _close(node[field], values[field]), (key, field, node[field], values[field])
    for key, values in expected["nodes"]["values"].items():
        node = by_id[str(ids[key])]
        for field in ("e", "sigma", "p80", "p90", "sum_o", "sum_r", "sum_p"):
            assert _close(node[field], values[field]), (key, field, node[field], values[field])
    totals = tree["totals"]
    for group in ("works", "pm", "total"):
        for field, value in expected[group]["values"].items():
            if field in totals[group]:
                assert _close(totals[group][field], value), (group, field)
    assert totals["unaccounted_leaves"] == 0
    assert totals["nodes_limit"] == 5000
    assert totals["nodes_count"] == len(tree["nodes"]) == 19  # 18 узлов эталона и фаза УП
    # порядок: фазы по справочнику, УП — последней строкой (11.4 №15)
    roots = [n for n in tree["nodes"] if n["parent_id"] is None]
    assert roots[-1]["title"] == "Управление проектом"
    assert _close(roots[-1]["e"], expected["pm"]["values"]["e"])
    assert tree["project_version"] == 1
    assert len(tree["branch_statuses"]) == 5
    assert all(
        b["status"] == "not_started" and not b["has_expert"] for b in tree["branch_statuses"]
    )


async def test_tree_leaf_states_and_permissions(world: World, db_session: AsyncSession) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid, ids = await _portal(world, moderator)
    leaf = await db_session.get(Node, ids["n-auth"])
    leaf.o, leaf.r, leaf.p = Decimal(20), Decimal(12), Decimal(8)  # O > R — неверная оценка
    other = await db_session.get(Node, ids["n-profile"])
    other.p = None
    await db_session.flush()
    tree = (await moderator.get(f"/projects/{pid}/tree")).json()
    by_id = {n["id"]: n for n in tree["nodes"]}
    assert by_id[str(ids["n-auth"])]["leaf_state"] == "invalid"
    assert by_id[str(ids["n-auth"])]["e"] is None
    assert by_id[str(ids["n-profile"])]["leaf_state"] == "empty"
    assert tree["totals"]["unaccounted_leaves"] == 2

    stranger = await world.actor(SystemRole.MODERATOR)
    assert (await stranger.get(f"/projects/{pid}/tree")).status_code == 404
    expert = await world.actor()
    backend = (
        await db_session.scalars(select(Discipline.id).where(Discipline.name == "Бэкенд"))
    ).one()
    db_session.add(
        ProjectMember(
            project_id=pid, user_id=expert.id, role=ProjectRole.EXPERT, discipline_id=backend
        )
    )
    await db_session.execute(
        text("UPDATE projects SET status = 'estimation' WHERE id = :p"), {"p": pid}
    )
    await db_session.flush()
    seen = await expert.get(f"/projects/{pid}/tree")
    assert seen.status_code == 200
    has_expert = {b["discipline_id"]: b["has_expert"] for b in seen.json()["branch_statuses"]}
    assert has_expert[str(backend)] is True


def _coverage_active() -> bool:
    coverage = sys.modules.get("coverage")
    return coverage is not None and coverage.Coverage.current() is not None


@pytest.mark.spec("NFR-LIM-01")
@pytest.mark.spec("BR-TREE-06")
async def test_tree_of_5000_nodes_is_fast(world: World, db_session: AsyncSession) -> None:
    """5 000 узлов собираются и считаются быстро (CORE-014 «≤ 1 с на dev-стенде»)."""
    moderator = await world.actor(SystemRole.MODERATOR)
    pid, ids = await _portal(world, moderator)
    branch = await db_session.get(Node, ids["n-ph-dev-d-backend"])
    rows: list[dict[str, Any]] = []
    positions = keys_after("b00", 5000 - 19)
    parents = [branch.id]
    for i, position in enumerate(positions):
        node_id = uuid7()
        is_group = i % 10 == 0
        rows.append(
            {
                "id": node_id,
                "project_id": pid,
                "parent_id": parents[-1] if not is_group else branch.id,
                "kind": "item",
                "phase_id": branch.phase_id,
                "discipline_id": branch.discipline_id,
                "title": f"Узел {i}",
                "position": position,
                "o": None if is_group else Decimal(1),
                "r": None if is_group else Decimal(2),
                "p": None if is_group else Decimal(4),
                "multiplier": 1,
            }
        )
        if is_group:
            parents.append(node_id)
    await db_session.execute(Node.__table__.insert(), rows)
    project = await db_session.get(Project, pid)
    started = time.perf_counter()
    tree = await load_tree(db_session, project)
    elapsed = time.perf_counter() - started
    assert tree["totals"]["nodes_count"] == 5000
    # Бюджет NFR-LIM-01 — для кода без инструментирования. Под coverage (CI) трассировка каждой
    # строки замедляет сборку в 3–4 раза, поэтому бюджет там втрое больше.
    budget = 3.0 if _coverage_active() else 1.0
    assert elapsed < budget, f"дерево из 5 000 узлов собрано за {elapsed:.2f} с (бюджет {budget} с)"
