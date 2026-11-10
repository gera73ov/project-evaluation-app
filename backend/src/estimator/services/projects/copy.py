"""CORE-023 · копирование проекта (SPEC FR-PRJ-02, 3.3; 15.2 ``POST /projects/{id}/copy``).

Новый проект в «Подготовке» с настройками, фазами, дисциплинами и профилями, командой, деревом и
локальными типами узлов источника. Не копируются обсуждения, история узлов, снимки, корзина,
отметки «Проверено», «Результат пресейла» (исход, сумма договора) и журнал. Ставки, валюта и НДС
копируются, только если копирует модератор исходного проекта. Толкования —
agents/journal/DEC-20261109-core-project-copy.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue, NodeKind, ProjectRole, ProjectStatus
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.projects import (
    BranchStatus,
    Project,
    ProjectDiscipline,
    ProjectMember,
    ProjectPhase,
)
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.security import audit
from estimator.services import money
from estimator.services.common import app_today
from estimator.services.projects import journal, totals
from estimator.services.tree.load import NODES_LIMIT

NAME_MAX = 200
COPY_SUFFIX = " (копия)"
S = BranchStatusValue


def copy_name(name: str) -> str:
    """Имя копии по умолчанию: «<имя> (копия)», в пределах 200 символов."""
    return name[: NAME_MAX - len(COPY_SUFFIX)] + COPY_SUFFIX


async def _is_moderator(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.role == ProjectRole.MODERATOR,
            )
        )
    ) is not None


async def _local_types(
    db: AsyncSession, source: Project, target: Project, user_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """Локальные типы источника → копии в новом проекте (FR-TREE-03)."""
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    rows = (await db.scalars(select(NodeType).where(NodeType.project_id == source.id))).all()
    for t in rows:
        new = NodeType(
            id=uuid7(),
            name=t.name,
            icon=t.icon,
            norms=list(t.norms),
            is_active=t.is_active,
            is_system=False,
            project_id=target.id,
            proposal_status=t.proposal_status,
            merged_into_id=t.merged_into_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(new)
        mapping[t.id] = new.id
    return mapping


async def _tree(
    db: AsyncSession,
    source: Project,
    target: Project,
    types: dict[uuid.UUID, uuid.UUID],
    user_id: uuid.UUID,
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Живое дерево источника без «Проверено» и истории; пары веток, где есть узлы."""
    nodes = list(
        (
            await db.scalars(
                select(Node).where(Node.project_id == source.id, Node.deleted_at.is_(None))
            )
        ).all()
    )
    if len(nodes) > NODES_LIMIT:  # pragma: no cover — у источника тот же лимит BR-TREE-06
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=0, requested=len(nodes))
    # родители раньше детей: вставка идёт в порядке add, FK parent_id не отложенный
    children: dict[uuid.UUID | None, list[Node]] = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    ordered: list[Node] = []
    frontier = children.get(None, [])
    while frontier:
        ordered.extend(frontier)
        frontier = [c for p in frontier for c in children.get(p.id, [])]
    nodes = ordered
    ids = {n.id: uuid7() for n in nodes}
    filled: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for n in nodes:
        if n.kind is NodeKind.ITEM and n.discipline_id is not None:
            filled.add((n.phase_id, n.discipline_id))
        db.add(
            Node(
                id=ids[n.id],
                project_id=target.id,
                parent_id=ids[n.parent_id] if n.parent_id else None,
                kind=n.kind,
                phase_id=n.phase_id,
                discipline_id=n.discipline_id,
                type_id=types.get(n.type_id, n.type_id) if n.type_id else None,
                title=n.title,
                position=n.position,
                o=n.o,
                r=n.r,
                p=n.p,
                multiplier=n.multiplier,
                comment_lines=list(n.comment_lines) if n.comment_lines else None,
                self_review=False,
                version=1,
                field_versions={},
                created_by=user_id,
                updated_by=user_id,
            )
        )
    return filled


async def copy_project(
    db: AsyncSession, principal: Principal, source: Project, name: str | None
) -> tuple[Project, bool]:
    """Копия проекта (FR-PRJ-02); проект и признак «ставки скопированы»."""
    user_id = principal.user_id
    title = name.strip() if name is not None else copy_name(source.name)
    if len(title) < 3:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Название — от 3 до 200 символов",
            errors=[{"field": "/name", "code": "too_short", "message": "Минимум 3 символа"}],
        )
    deadline = source.deadline
    if deadline is not None and deadline < await app_today(db):
        deadline = None  # прошедший срок в новом проекте не нужен (BR-PRJ-08)
    target = Project(
        id=uuid7(),
        name=title,
        customer=source.customer,
        description=source.description,
        detail_level=source.detail_level,
        quote_figure=source.quote_figure,
        pm_percent=source.pm_percent,
        pm_percent_reason=source.pm_percent_reason,
        duration_weeks=source.duration_weeks,
        deadline=deadline,
        status=ProjectStatus.PREPARATION,
        version=1,
        copied_from_id=source.id,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(target)
    await db.flush()

    for phase in (
        await db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == source.id))
    ).all():
        db.add(
            ProjectPhase(
                project_id=target.id,
                phase_id=phase.phase_id,
                is_enabled=phase.is_enabled,
                in_pm_base=phase.in_pm_base,
            )
        )
    for d in (
        await db.scalars(select(ProjectDiscipline).where(ProjectDiscipline.project_id == source.id))
    ).all():
        db.add(
            ProjectDiscipline(
                project_id=target.id,
                discipline_id=d.discipline_id,
                profile_id=d.profile_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )
    types = await _local_types(db, source, target, user_id)
    await db.flush()
    filled = await _tree(db, source, target, types, user_id)
    for row in (
        await db.scalars(select(BranchStatus).where(BranchStatus.project_id == source.id))
    ).all():
        key = (row.phase_id, row.discipline_id)
        status = (
            S.NOT_NEEDED
            if row.status is S.NOT_NEEDED
            else S.DRAFT
            if key in filled
            else S.NOT_STARTED
        )
        db.add(
            BranchStatus(
                project_id=target.id,
                phase_id=row.phase_id,
                discipline_id=row.discipline_id,
                status=status,
                changed_by=user_id,
            )
        )

    copier_seen = False
    for m in (
        await db.scalars(select(ProjectMember).where(ProjectMember.project_id == source.id))
    ).all():
        copier_seen |= m.user_id == user_id and m.role is ProjectRole.MODERATOR
        db.add(
            ProjectMember(
                project_id=target.id,
                user_id=m.user_id,
                role=m.role,
                discipline_id=m.discipline_id,
                is_reviewer=m.is_reviewer,
                added_by_admin_self=m.added_by_admin_self,
                created_by=user_id,
                updated_by=user_id,
            )
        )
    if not copier_seen:  # pragma: no cover — право project.copy есть только у модератора
        db.add(
            ProjectMember(
                project_id=target.id,
                user_id=user_id,
                role=ProjectRole.MODERATOR,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    rates = await _is_moderator(db, source.id, user_id)
    await money.create_defaults(db, target.id, user_id)
    await db.flush()
    totals.schedule(db, target.id)  # кэш итогов для «Моих оценок» (CORE-026)
    if rates:
        await money.copy_settings(db, source.id, target.id, user_id)
    await db.flush()
    journal.record(
        db,
        target.id,
        user_id,
        "project.created",
        {"name": (None, target.name), "copied_from": (None, str(source.id))},
    )
    await audit.write(
        db,
        "project.created",
        user_id=user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project",
        object_id=target.id,
        project_id=target.id,
        details={"copied_from": str(source.id), "rates_copied": rates},
    )
    return target, rates
