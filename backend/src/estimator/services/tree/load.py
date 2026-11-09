"""CORE-014 · дерево проекта с расчётом при выдаче (SPEC 5.1, 14.3, ARCH-03, ARCH-04, BR-TREE-01,
BR-TREE-04…06, NFR-LIM-01; 15.2 ``GET /projects/{id}/tree``).

Все живые узлы читаются одним запросом (14.3), дерево собирается в памяти, суммы считает
:mod:`estimator.domain.calc` (CORE-003/004) — тот же код, что проверяют эталонные фикстуры.
Ответ без денег (SEC-AUTHZ-04): денежных ключей нет ни в узлах, ни в итогах.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.auth.policy import read_settings
from estimator.db.enums import NodeKind, ProjectRole
from estimator.db.models.dictionaries import Discipline, Phase
from estimator.db.models.projects import (
    BranchStatus,
    Project,
    ProjectDiscipline,
    ProjectMember,
    ProjectPhase,
)
from estimator.db.models.tree import Node
from estimator.db.models.users import User
from estimator.domain import calc
from estimator.domain.calc.analytics import DEFAULT_LARGE_LEAF_HOURS, decomposition
from estimator.services.common import hours, user_ref

NODES_LIMIT = 5000  # BR-TREE-06
NODES_WARNING = 4500
DEPTH_LIMIT = 8  # уровней ниже ветки дисциплины (BR-TREE-05)


@dataclass(frozen=True)
class PhaseRow:
    phase_id: uuid.UUID
    name: str
    sort_order: int
    is_cross_cutting: bool
    is_enabled: bool
    in_pm_base: bool


@dataclass(frozen=True)
class DisciplineRow:
    discipline_id: uuid.UUID
    name: str
    profile_id: uuid.UUID
    has_expert: bool


async def project_phases(db: AsyncSession, project_id: uuid.UUID) -> list[PhaseRow]:
    """Фазы проекта в порядке справочника (5.1: «порядок задаётся справочником»)."""
    rows = await db.execute(
        select(
            ProjectPhase.phase_id,
            Phase.name,
            Phase.sort_order,
            Phase.is_cross_cutting,
            ProjectPhase.is_enabled,
            ProjectPhase.in_pm_base,
        )
        .join(Phase, Phase.id == ProjectPhase.phase_id)
        .where(ProjectPhase.project_id == project_id)
        .order_by(Phase.sort_order, Phase.name)
    )
    return [PhaseRow(*r) for r in rows.all()]


async def project_disciplines(db: AsyncSession, project_id: uuid.UUID) -> list[DisciplineRow]:
    experts = (
        select(ProjectMember.discipline_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.EXPERT)
        .distinct()
        .scalar_subquery()
    )
    rows = await db.execute(
        select(
            ProjectDiscipline.discipline_id,
            Discipline.name,
            ProjectDiscipline.profile_id,
            ProjectDiscipline.discipline_id.in_(experts),
        )
        .join(Discipline, Discipline.id == ProjectDiscipline.discipline_id)
        .where(ProjectDiscipline.project_id == project_id)
        .order_by(Discipline.name)
    )
    return [DisciplineRow(*r) for r in rows.all()]


async def live_nodes(db: AsyncSession, project_id: uuid.UUID) -> list[Any]:
    """Все живые узлы проекта одним запросом (14.3).

    Строки таблицы, а не объекты ORM: на 5 000 узлах сборка объектов и identity map занимали
    большую часть бюджета NFR-LIM-01. Поля читаются теми же именами, что у :class:`Node`.
    """
    table = Node.__table__
    rows = await db.execute(
        select(table).where(table.c.project_id == project_id, table.c.deleted_at.is_(None))
    )
    return list(rows.all())


async def count_live_nodes(db: AsyncSession, project_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(Node.project_id == project_id, Node.deleted_at.is_(None))
    return int(await db.scalar(stmt) or 0)


def _thresholds(raw: Any) -> Mapping[calc.DetailLevel, Decimal | None]:
    if not isinstance(raw, Mapping):
        return DEFAULT_LARGE_LEAF_HOURS
    out = dict(DEFAULT_LARGE_LEAF_HOURS)
    for level in (calc.DetailLevel.MEDIUM, calc.DetailLevel.DETAILED):
        value = raw.get(level.value)
        if isinstance(value, int | float | str):
            out[level] = Decimal(str(value))
    return out


def calc_input(
    project: Project,
    phases: list[PhaseRow],
    disciplines: list[DisciplineRow],
    nodes: list[Node],
    statuses: Mapping[tuple[uuid.UUID, uuid.UUID], str],
) -> calc.ProjectInput:
    """Вход расчётного модуля из строк БД (формат CORE-001)."""
    return calc.ProjectInput(
        pm_percent=project.pm_percent,
        quote_figure=calc.QuoteFigure(str(project.quote_figure)),
        detail_level=calc.DetailLevel(str(project.detail_level)),
        phases=[
            calc.Phase(
                id=str(p.phase_id),
                name=p.name,
                is_cross_cutting=p.is_cross_cutting,
                in_pm_base=p.in_pm_base,
                enabled=p.is_enabled,
            )
            for p in phases
        ],
        disciplines=[calc.Discipline(id=str(d.discipline_id), name=d.name) for d in disciplines],
        nodes=[
            calc.Node(
                id=str(n.id),
                parent_id=str(n.parent_id) if n.parent_id else None,
                kind=calc.NodeKind(str(n.kind)),
                phase_id=str(n.phase_id),
                discipline_id=str(n.discipline_id) if n.discipline_id else None,
                type=str(n.type_id) if n.type_id else None,
                title=n.title,
                o=n.o,
                r=n.r,
                p=n.p,
                multiplier=n.multiplier,
            )
            for n in nodes
        ],
        branch_status={(str(ph), str(d)): calc.BranchStatus(s) for (ph, d), s in statuses.items()},
    )


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _figures(totals: calc.Totals | calc.Figures) -> dict[str, str | None]:
    return {
        "e": hours(totals.e),
        "sigma": hours(totals.sigma),
        "p80": hours(totals.p80),
        "p90": hours(totals.p90),
    }


def _ordered(nodes: list[Node], phase_order: Mapping[uuid.UUID, int]) -> list[Node]:
    """Прямой обход: фазы по справочнику, соседи по ``position``."""
    children: dict[uuid.UUID | None, list[Node]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    for parent, items in children.items():
        if parent is None:
            items.sort(key=lambda n: (phase_order.get(n.phase_id, 1 << 30), n.position, n.id))
        else:
            items.sort(key=lambda n: (n.position, n.id))
    out: list[Node] = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(children.get(node.id, [])))
    return out


@dataclass
class Computed:
    phases: list[PhaseRow]
    disciplines: list[DisciplineRow]
    nodes: list[Any]
    status_rows: list[Any]
    result: calc.ProjectResult
    large: set[str]
    repeating: set[str]


async def compute(db: AsyncSession, project: Project) -> Computed:
    """Строки дерева и расчёт: общий шаг :func:`load_tree` и :func:`mutation_view`."""
    phases = await project_phases(db, project.id)
    disciplines = await project_disciplines(db, project.id)
    nodes = await live_nodes(db, project.id)
    status_rows = list(
        (
            await db.execute(
                select(BranchStatus, User.full_name, User.status)
                .outerjoin(User, User.id == BranchStatus.changed_by)
                .where(BranchStatus.project_id == project.id)
            )
        ).all()
    )
    statuses = {(b.phase_id, b.discipline_id): str(b.status) for b, _, _ in status_rows}
    result = calc.calculate(calc_input(project, phases, disciplines, nodes, statuses))
    settings = await read_settings(db, "method.large_leaf_hours")
    flags = decomposition(result, _thresholds(settings.get("method.large_leaf_hours")))
    return Computed(
        phases, disciplines, nodes, status_rows, result, set(flags.large), set(flags.repeating)
    )


async def _reviewers(db: AsyncSession, nodes: list[Any]) -> dict[uuid.UUID, dict[str, Any]]:
    reviewer_ids = {n.reviewed_by for n in nodes if n.reviewed_by}
    if not reviewer_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.full_name, User.status).where(User.id.in_(reviewer_ids))
    )
    return {uid: user_ref(uid, name, is_active=str(st) == "active") for uid, name, st in rows}


async def mutation_view(
    db: AsyncSession, project: Project, node_id: uuid.UUID
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str | None]]:
    """Узел, его предки (id, E, σ) от родителя к корню и итог проекта — ответ правки (15.3).

    Считает проект целиком, но собирает выходные строки только для узла и предков.
    """
    c = await compute(db, project)
    by_id = {n.id: n for n in c.nodes}
    node = by_id[node_id]
    reviewers = await _reviewers(db, [node])
    cross_cutting = {p.phase_id for p in c.phases if p.is_cross_cutting}
    out = _node_out(node, c.result, reviewers, cross_cutting, c.large, c.repeating)
    ancestors = []
    parent = node.parent_id
    while parent is not None:
        row = by_id[parent]
        figures = _node_out(row, c.result, {}, cross_cutting, c.large, c.repeating)
        ancestors.append({"id": figures["id"], "e": figures["e"], "sigma": figures["sigma"]})
        parent = row.parent_id
    return out, ancestors, _figures(c.result.total)


async def load_tree(db: AsyncSession, project: Project) -> dict[str, Any]:
    """Тело ответа ``Tree`` (contracts/openapi.yaml): узлы, статусы веток, итоги, версия."""
    c = await compute(db, project)
    phases, disciplines, nodes, status_rows = c.phases, c.disciplines, c.nodes, c.status_rows
    result, large, repeating = c.result, c.large, c.repeating
    reviewers = await _reviewers(db, nodes)

    cross_cutting = {p.phase_id for p in phases if p.is_cross_cutting}
    order = {p.phase_id: i for i, p in enumerate(phases)}
    out_nodes = [
        _node_out(n, result, reviewers, cross_cutting, large, repeating)
        for n in _ordered(nodes, order)
    ]
    has_expert = {d.discipline_id: d.has_expert for d in disciplines}
    branch_statuses = [
        {
            "phase_id": str(b.phase_id),
            "discipline_id": str(b.discipline_id),
            "status": str(b.status),
            "changed_by": (
                user_ref(b.changed_by, name, is_active=str(st) == "active")
                if b.changed_by and name
                else None
            ),
            "changed_at": b.changed_at.isoformat().replace("+00:00", "Z"),
            "open_questions": 0,  # счётчик вопросов подключит CORE-040
            "has_expert": has_expert.get(b.discipline_id, False),
        }
        for b, name, st in status_rows
    ]
    return {
        "project_version": project.version,
        "nodes": out_nodes,
        "branch_statuses": branch_statuses,
        "totals": {
            "works": _figures(result.works),
            "pm": _figures(result.pm),
            "total": _figures(result.total),
            "unaccounted_leaves": result.unaccounted_leaves,
            "nodes_count": len(nodes),
            "nodes_limit": NODES_LIMIT,
        },
    }


def _node_out(
    node: Node,
    result: calc.ProjectResult,
    reviewers: Mapping[uuid.UUID, dict[str, Any]],
    cross_cutting: set[uuid.UUID],
    large: set[str],
    repeating: set[str],
) -> dict[str, Any]:
    key = str(node.id)
    calc_node = result.tree[key]
    out: dict[str, Any] = {
        "id": key,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "kind": str(node.kind),
        "phase_id": str(node.phase_id),
        "discipline_id": str(node.discipline_id) if node.discipline_id else None,
        "type_id": str(node.type_id) if node.type_id else None,
        "title": node.title,
        "position": node.position,
        "o": _dec(node.o),
        "r": _dec(node.r),
        "p": _dec(node.p),
        "multiplier": node.multiplier,
        "comment_lines": node.comment_lines,
        "reviewed_by": reviewers.get(node.reviewed_by) if node.reviewed_by else None,
        "reviewed_at": (
            node.reviewed_at.isoformat().replace("+00:00", "Z") if node.reviewed_at else None
        ),
        "self_review": node.self_review,
        "version": node.version,
        "field_versions": node.field_versions,
        "is_large": key in large,
        "is_repeating": key in repeating,
        # счётчики обсуждений подключат CORE-040…043 (этап 3)
        "messages_count": 0,
        "open_questions": 0,
        "questions_to_me": 0,
    }
    if node.kind is NodeKind.PHASE and node.phase_id in cross_cutting:
        # строка «Управление проектом»: без листьев, E = k · E базы (6.3, 11.4 №15)
        out |= _figures(result.pm) | {"sum_o": None, "sum_r": None, "sum_p": None}
        out |= {"leaf_state": None, "unaccounted_leaves": 0}
        return out
    leaf = calc_node.leaf
    if calc_node.is_leaf and leaf is not None:
        counted = leaf.state.counted
        out |= {
            "e": hours(leaf.e) if counted else None,
            "sigma": hours(leaf.sigma) if counted else None,
            "p80": hours(leaf.p80) if counted else None,
            "p90": hours(leaf.p90) if counted else None,
            "sum_o": None,
            "sum_r": None,
            "sum_p": None,
            "leaf_state": str(leaf.state),
            "unaccounted_leaves": 0 if counted else 1,
        }
        return out
    totals = calc_node.totals
    out |= _figures(totals) | {
        "sum_o": hours(totals.sum_o),
        "sum_r": hours(totals.sum_r),
        "sum_p": hours(totals.sum_p),
        "leaf_state": None,
        "unaccounted_leaves": totals.unaccounted,
    }
    return out


def node_event(node: Node) -> dict[str, Any]:
    """Узел для событий WebSocket (``$defs/Node`` ws-events): без сумм и без денег (ARCH-03)."""
    return {
        "id": str(node.id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "kind": str(node.kind),
        "phase_id": str(node.phase_id),
        "discipline_id": str(node.discipline_id) if node.discipline_id else None,
        "type_id": str(node.type_id) if node.type_id else None,
        "title": node.title,
        "position": node.position,
        "o": _dec(node.o),
        "r": _dec(node.r),
        "p": _dec(node.p),
        "multiplier": node.multiplier,
        "comment_lines": node.comment_lines,
        "reviewed_by": str(node.reviewed_by) if node.reviewed_by else None,
        "reviewed_at": (
            node.reviewed_at.isoformat().replace("+00:00", "Z") if node.reviewed_at else None
        ),
        "self_review": node.self_review,
        "version": node.version,
        "field_versions": node.field_versions,
    }
