"""CORE-014 · дерево проекта с расчётом при выдаче (SPEC 5.1, 14.3, ARCH-03, ARCH-04, BR-TREE-01,
BR-TREE-04…06, NFR-LIM-01; 15.2 ``GET /projects/{id}/tree``).

Все живые узлы читаются одним запросом (14.3), дерево собирается в памяти, суммы считает
:mod:`estimator.domain.calc` (CORE-003/004) — тот же код, что проверяют эталонные фикстуры.
Ответ без денег (SEC-AUTHZ-04): денежных ключей нет ни в узлах, ни в итогах.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.auth.policy import read_settings
from estimator.db.enums import CommentTagCategory, NodeKind, ProjectRole
from estimator.db.models.dictionaries import CommentTag, Discipline, Phase
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
from estimator.domain.calc import incremental
from estimator.domain.calc.analytics import (
    DEFAULT_LARGE_LEAF_HOURS,
    decomposition,
    large_leaf_threshold,
    leaf_candidate,
)
from estimator.services.common import hours, user_ref
from estimator.services.discussions.counters import Counters, tree_counters
from estimator.services.tree import calc_cache

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


#: Колонки узла, которых хватает расчёту и обходу предков: без jsonb ``field_versions`` и
#: ``comment_lines``, разбор которых на 2 000 узлах заметно удлинял каждую правку (QA-019)
CALC_COLUMNS = (
    "id",
    "parent_id",
    "kind",
    "phase_id",
    "discipline_id",
    "type_id",
    "title",
    "o",
    "r",
    "p",
    "multiplier",
)


async def live_nodes(
    db: AsyncSession, project_id: uuid.UUID, columns: Sequence[str] | None = None
) -> list[Any]:
    """Все живые узлы проекта одним запросом (14.3); ``columns`` — только эти колонки.

    Строки таблицы, а не объекты ORM: на 5 000 узлах сборка объектов и identity map занимали
    большую часть бюджета NFR-LIM-01. Поля читаются теми же именами, что у :class:`Node`.
    """
    table = Node.__table__
    picked = [table] if columns is None else [table.c[name] for name in columns]
    rows = await db.execute(
        select(*picked).where(table.c.project_id == project_id, table.c.deleted_at.is_(None))
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


async def compute(
    db: AsyncSession, project: Project, columns: Sequence[str] | None = None
) -> Computed:
    """Строки дерева и расчёт: общий шаг :func:`load_tree` и :func:`mutation_view`.

    ``columns`` — какие колонки узлов читать (:data:`CALC_COLUMNS`, если строки нужны только
    расчёту); по умолчанию все.
    """
    phases = await project_phases(db, project.id)
    disciplines = await project_disciplines(db, project.id)
    nodes = await live_nodes(db, project.id, columns)
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
    db: AsyncSession, project: Project, node_id: uuid.UUID, viewer: uuid.UUID | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str | None]]:
    """Узел, его предки (id, E, σ) от родителя к корню и итог проекта — ответ правки (15.3).

    Расчёт берётся из кэша экземпляра и догоняется по ``change_log``: пересчитываются только
    изменённые узлы и их предки (:mod:`estimator.services.tree.calc_cache`). Числа те же, что
    у :func:`load_tree`.
    """
    phases = await project_phases(db, project.id)
    disciplines = await project_disciplines(db, project.id)
    statuses = {
        (ph, d): str(st)
        for ph, d, st in (
            await db.execute(
                select(
                    BranchStatus.phase_id, BranchStatus.discipline_id, BranchStatus.status
                ).where(BranchStatus.project_id == project.id)
            )
        ).all()
    }
    state = await calc_cache.project_state(
        db,
        project,
        calc_cache.fingerprint(project, phases, disciplines, statuses),
        lambda rows: calc_input(project, phases, disciplines, list(rows), statuses),
        CALC_COLUMNS,
    )
    tree, pm = state.tree, state.summary.pm
    table = Node.__table__
    node = (await db.execute(select(table).where(table.c.id == node_id))).one()
    reviewers = await _reviewers(db, [node])
    cross_cutting = {str(p.phase_id) for p in phases if p.is_cross_cutting}
    settings = await read_settings(db, "method.large_leaf_hours")
    threshold = large_leaf_threshold(
        calc.DetailLevel(str(project.detail_level)),
        _thresholds(settings.get("method.large_leaf_hours")),
    )
    flags = leaf_candidate(tree[str(node.id)], threshold)
    out = _node_out(
        node,
        tree,
        pm,
        reviewers,
        cross_cutting,
        {str(node.id)} if flags and flags.large else set(),
        {str(node.id)} if flags and flags.repeating else set(),
    )
    out |= (await tree_counters(db, project.id, viewer)).node(node.id)
    ancestors = []
    parent = tree[str(node.id)].node.parent_id
    while parent is not None:
        row = tree[parent]
        figures = _node_figures(row.node, tree, pm, cross_cutting)
        ancestors.append({"id": parent, "e": figures["e"], "sigma": figures["sigma"]})
        parent = row.node.parent_id
    return out, ancestors, _figures(state.summary.total)


async def load_tree(
    db: AsyncSession, project: Project, viewer: uuid.UUID | None = None
) -> dict[str, Any]:
    """Тело ответа ``Tree`` (contracts/openapi.yaml): узлы, статусы веток, итоги, версия.

    ``viewer`` — зритель для счётчика «вопросы мне» (без него — 0). Расчёт берётся из кэша
    экземпляра и сверяется с прочитанными строками (:func:`calc_cache.state_for_rows`), а
    расчётная часть строки узла переиспользуется, пока результат узла не изменился (QA-020).
    """
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
    state = calc_cache.state_for_rows(
        db,
        project,
        calc_cache.fingerprint(project, phases, disciplines, statuses),
        lambda rows: calc_input(project, phases, disciplines, list(rows), statuses),
        nodes,
    )
    settings = await read_settings(db, "method.large_leaf_hours")
    threshold = large_leaf_threshold(
        calc.DetailLevel(str(project.detail_level)),
        _thresholds(settings.get("method.large_leaf_hours")),
    )
    counters = await tree_counters(db, project.id, viewer)
    reviewers = await _reviewers(db, nodes)

    cross_cutting = {str(p.phase_id) for p in phases if p.is_cross_cutting}
    order = {p.phase_id: i for i, p in enumerate(phases)}
    tree, summary = state.tree, state.summary
    out_nodes = [
        _tree_node(n, state, threshold, reviewers, cross_cutting, counters)
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
            "open_questions": counters.branches[(b.phase_id, b.discipline_id)],
            "has_expert": has_expert.get(b.discipline_id, False),
        }
        for b, name, st in status_rows
    ]
    return {
        "project_version": project.version,
        "nodes": out_nodes,
        "branch_statuses": branch_statuses,
        "totals": {
            "works": _figures(summary.works),
            "pm": _figures(summary.pm),
            "total": _figures(summary.total),
            "unaccounted_leaves": summary.unaccounted_leaves,
            "nodes_count": len(nodes),
            "nodes_limit": NODES_LIMIT,
            "open_questions": counters.project_open,
            "questions_to_me": counters.project_to_me,
            "risks": await _risks(db, nodes, tree),
        },
    }


def _tree_node(
    node: Any,
    state: incremental.CalcState,
    threshold: Decimal | None,
    reviewers: Mapping[uuid.UUID, dict[str, Any]],
    cross_cutting: set[str],
    counters: Counters,
) -> dict[str, Any]:
    """Строка узла для :func:`load_tree`; расчётная часть — из ``state.memo``.

    Расчётная часть зависит только от результата узла (тот же объект — те же числа) и порога
    «крупного» листа. Строка «Управление проектом» зависит ещё от итогов и не кэшируется.
    """
    key = str(node.id)
    result = state.tree[key]
    cached = state.memo.get(key)
    if cached is not None and cached[0] is result and cached[1] == threshold:
        calc_part = cached[2]
    else:
        calc_part = _calc_part(result, state.summary.pm, threshold, cross_cutting)
        if not (result.node.kind is calc.NodeKind.PHASE and result.node.phase_id in cross_cutting):
            state.memo[key] = (result, threshold, calc_part)
    return {
        **calc_part,
        "position": node.position,
        "comment_lines": node.comment_lines,
        "reviewed_by": reviewers.get(node.reviewed_by) if node.reviewed_by else None,
        "reviewed_at": (
            node.reviewed_at.isoformat().replace("+00:00", "Z") if node.reviewed_at else None
        ),
        "self_review": node.self_review,
        "version": node.version,
        "field_versions": node.field_versions,
        **counters.node(node.id),  # FR-DISC-04
    }


def _calc_part(
    result: Any, pm: calc.PmResult, threshold: Decimal | None, cross_cutting: set[str]
) -> dict[str, Any]:
    """Поля строки узла, которые определяет узел расчёта (:class:`calc.Node`) и его результат."""
    n = result.node
    flags = leaf_candidate(result, threshold)
    return {
        "id": n.id,
        "parent_id": n.parent_id,
        "kind": str(n.kind),
        "phase_id": n.phase_id,
        "discipline_id": n.discipline_id,
        "type_id": n.type,
        "title": n.title,
        "o": _dec(n.o),
        "r": _dec(n.r),
        "p": _dec(n.p),
        "multiplier": n.multiplier,
        "is_large": bool(flags and flags.large),
        "is_repeating": bool(flags and flags.repeating),
        **_figures_of(result, pm, n.kind is calc.NodeKind.PHASE and n.phase_id in cross_cutting),
    }


async def _risks(db: AsyncSession, nodes: list[Any], tree: calc.TreeResult) -> int:
    """Счётчик рисков (FR-TREE-11): живые листья с меткой категории «Риск» в комментарии."""
    risk = {
        str(t)
        for t in await db.scalars(
            select(CommentTag.id).where(CommentTag.category == CommentTagCategory.RISK)
        )
    }
    return sum(
        1
        for n in nodes
        if tree[str(n.id)].is_leaf
        and any(str(line.get("tag_id")) in risk for line in (n.comment_lines or []))
    )


def _node_out(
    node: Node,
    tree: calc.TreeResult,
    pm: calc.PmResult,
    reviewers: Mapping[uuid.UUID, dict[str, Any]],
    cross_cutting: set[str],
    large: set[str],
    repeating: set[str],
    counters: Counters | None = None,
) -> dict[str, Any]:
    key = str(node.id)
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
        **(counters or Counters()).node(node.id),  # FR-DISC-04
    }
    return out | _node_figures(node, tree, pm, cross_cutting)


def _node_figures(
    node: Any, tree: calc.TreeResult, pm: calc.PmResult, cross_cutting: set[str]
) -> dict[str, Any]:
    """Расчётные поля узла (E, σ, P80, P90, суммы, состояние листа); нужны id, kind, phase_id.

    ``node`` — строка БД или узел расчёта (:class:`calc.Node`, идентификаторы — строки).
    """
    is_pm_row = str(node.kind) == NodeKind.PHASE and str(node.phase_id) in cross_cutting
    return _figures_of(tree[str(node.id)], pm, is_pm_row)


def _figures_of(calc_node: Any, pm: calc.PmResult, is_pm_row: bool) -> dict[str, Any]:
    if is_pm_row:
        # строка «Управление проектом»: без листьев, E = k · E базы (6.3, 11.4 №15)
        out = _figures(pm) | {"sum_o": None, "sum_r": None, "sum_p": None}
        return out | {"leaf_state": None, "unaccounted_leaves": 0}
    leaf = calc_node.leaf
    if calc_node.is_leaf and leaf is not None:
        counted = leaf.state.counted
        return {
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
    totals = calc_node.totals
    return _figures(totals) | {
        "sum_o": hours(totals.sum_o),
        "sum_r": hours(totals.sum_r),
        "sum_p": hours(totals.sum_p),
        "leaf_state": None,
        "unaccounted_leaves": totals.unaccounted,
    }


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
