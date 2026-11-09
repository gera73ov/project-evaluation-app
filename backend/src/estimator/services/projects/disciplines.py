"""CORE-013 · дисциплины проекта и профиль ветки (SPEC FR-PRJ-04, 5.1, FR-TREE-04, 4.3;
15.2 ``POST /projects/{id}/disciplines``, ``PATCH/DELETE /projects/{id}/disciplines/{id}``).

* «Добавить дисциплину» — ветки во всех включённых фазах работ (не в сквозной «Управление
  проектом»), статус «не начато», профиль по умолчанию из справочника.
* Удаление — только если все ветки дисциплины пустые (иначе 409 ``BRANCH_NOT_EMPTY``); пустые
  ветки уходят в корзину одним пакетом, назначения экспертов на эту дисциплину снимаются.
* Профиль ветки один на все фазы; смена пишется в журнал проекта и не трогает статусы веток.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue, NodeKind, ProjectRole
from estimator.db.models.dictionaries import Discipline, DisciplineProfile, Phase
from estimator.db.models.projects import (
    BranchStatus,
    Project,
    ProjectDiscipline,
    ProjectMember,
    ProjectPhase,
)
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.services.common import emit, user_ref
from estimator.services.projects import journal
from estimator.services.tree.load import NODES_LIMIT, count_live_nodes, node_event
from estimator.services.tree.positions import key_between


def _validation(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": field, "code": "invalid", "message": message}],
    )


async def project_discipline_ids(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.scalars(
        select(ProjectDiscipline.discipline_id).where(ProjectDiscipline.project_id == project_id)
    )
    return set(rows.all())


async def _default_profile(db: AsyncSession, discipline: Discipline) -> uuid.UUID:
    if discipline.default_profile_id is not None:
        return discipline.default_profile_id
    first = await db.scalar(
        select(DisciplineProfile.id)
        .where(DisciplineProfile.discipline_id == discipline.id)
        .order_by(DisciplineProfile.name)
        .limit(1)
    )
    if first is None:
        raise _validation("/discipline_id", "У дисциплины нет профиля в справочнике")
    return first


async def _work_phase_nodes(db: AsyncSession, project_id: uuid.UUID) -> list[Node]:
    """Узлы включённых фаз работ (без сквозной фазы) — родители веток дисциплин."""
    stmt = (
        select(Node)
        .join(
            ProjectPhase,
            (ProjectPhase.project_id == Node.project_id) & (ProjectPhase.phase_id == Node.phase_id),
        )
        .join(Phase, Phase.id == Node.phase_id)
        .where(
            Node.project_id == project_id,
            Node.kind == NodeKind.PHASE,
            Node.deleted_at.is_(None),
            ProjectPhase.is_enabled,
            Phase.is_cross_cutting.is_(False),
        )
        .order_by(Phase.sort_order, Phase.name)
    )
    return list((await db.scalars(stmt)).all())


async def _discipline_names(db: AsyncSession, ids: set[uuid.UUID]) -> list[str]:
    rows = await db.scalars(select(Discipline.name).where(Discipline.id.in_(ids)))
    return sorted(rows.all())


async def add_discipline(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    discipline_id: uuid.UUID,
    *,
    publish_project: bool = True,
) -> list[Node]:
    """Добавить дисциплину: строки проекта, ветки во всех включённых фазах работ, события.

    ``publish_project=False`` — вызов из смены команды, которая сама сообщит об изменении.
    """
    discipline = await db.get(Discipline, discipline_id)
    if discipline is None or not discipline.is_active:
        raise _validation("/discipline_id", "Дисциплина не найдена среди активных")
    before = await project_discipline_ids(db, project.id)
    if discipline_id in before:
        raise ApiError("ALREADY_EXISTS", field="discipline_id")
    phase_nodes = await _work_phase_nodes(db, project.id)
    current = await count_live_nodes(db, project.id)
    if current + len(phase_nodes) > NODES_LIMIT:
        raise ApiError(
            "NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=len(phase_nodes)
        )
    db.add(
        ProjectDiscipline(
            project_id=project.id,
            discipline_id=discipline_id,
            profile_id=await _default_profile(db, discipline),
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
    )
    now = dt.datetime.now(dt.UTC)
    created: list[Node] = []
    for phase_node in phase_nodes:
        last = await db.scalar(
            select(func.max(Node.position)).where(
                Node.parent_id == phase_node.id, Node.deleted_at.is_(None)
            )
        )
        node = Node(
            id=uuid7(),
            project_id=project.id,
            parent_id=phase_node.id,
            kind=NodeKind.DISCIPLINE,
            phase_id=phase_node.phase_id,
            discipline_id=discipline_id,
            title=discipline.name,
            position=key_between(last, None),
            multiplier=1,
            self_review=False,
            version=1,
            field_versions={},
            created_by=principal.user_id,
            updated_by=principal.user_id,
        )
        db.add(node)
        created.append(node)
        status = await db.get(BranchStatus, (project.id, phase_node.phase_id, discipline_id))
        if status is None:
            db.add(
                BranchStatus(
                    project_id=project.id,
                    phase_id=phase_node.phase_id,
                    discipline_id=discipline_id,
                    status=BranchStatusValue.NOT_STARTED,
                )
            )
        else:  # строка осталась от выключенной фазы — ветка новая, «не начато»
            status.status = BranchStatusValue.NOT_STARTED
            status.changed_by = principal.user_id
            status.changed_at = now
    await db.flush()

    after = before | {discipline_id}
    journal.record(
        db,
        project.id,
        principal.user_id,
        "project.disciplines",
        {"disciplines": (await _discipline_names(db, before), await _discipline_names(db, after))},
    )
    author = user_ref(principal.user_id, principal.full_name)
    version = project.version
    for node in created:
        version = await emit(
            db, project.id, "node.created", {"node": node_event(node), "author": author}
        )
    if publish_project:
        version = await _publish_disciplines(db, principal, project.id)
    project.version = version
    return created


async def _publish_disciplines(
    db: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> int:
    """``project.updated`` с полным списком дисциплин проекта и их профилей."""
    rows = await db.execute(
        select(ProjectDiscipline.discipline_id, ProjectDiscipline.profile_id).where(
            ProjectDiscipline.project_id == project_id
        )
    )
    disciplines = sorted(
        ({"discipline_id": str(d), "profile_id": str(p)} for d, p in rows.all()),
        key=lambda item: item["discipline_id"],
    )
    return await emit(
        db,
        project_id,
        "project.updated",
        {
            "changes": {"disciplines": disciplines},
            "author": user_ref(principal.user_id, principal.full_name),
        },
    )


async def remove_discipline(
    db: AsyncSession, principal: Principal, project: Project, discipline_id: uuid.UUID
) -> int:
    """Удалить дисциплину из проекта, если все её ветки пустые; новая ``project_version``."""
    before = await project_discipline_ids(db, project.id)
    if discipline_id not in before:
        raise ApiError("NOT_FOUND")
    branches = list(
        (
            await db.scalars(
                select(Node.id).where(
                    Node.project_id == project.id,
                    Node.kind == NodeKind.DISCIPLINE,
                    Node.discipline_id == discipline_id,
                    Node.deleted_at.is_(None),
                )
            )
        ).all()
    )
    if branches:
        children = await db.scalar(
            select(func.count()).where(Node.parent_id.in_(branches), Node.deleted_at.is_(None))
        )
        if children:
            raise ApiError("BRANCH_NOT_EMPTY")
    batch = uuid7()
    if branches:
        await db.execute(
            update(Node)
            .where(Node.id.in_(branches))
            .values(
                deleted_at=dt.datetime.now(dt.UTC),
                deleted_batch_id=batch,
                deleted_by=principal.user_id,
            )
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        delete(BranchStatus).where(
            BranchStatus.project_id == project.id, BranchStatus.discipline_id == discipline_id
        )
    )
    experts = list(
        (
            await db.scalars(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.role == ProjectRole.EXPERT,
                    ProjectMember.discipline_id == discipline_id,
                )
            )
        ).all()
    )
    await db.execute(
        delete(ProjectDiscipline).where(
            ProjectDiscipline.project_id == project.id,
            ProjectDiscipline.discipline_id == discipline_id,
        )
    )
    after = before - {discipline_id}
    journal.record(
        db,
        project.id,
        principal.user_id,
        "project.disciplines",
        {"disciplines": (await _discipline_names(db, before), await _discipline_names(db, after))},
    )
    author = user_ref(principal.user_id, principal.full_name)
    version = project.version
    if branches:
        version = await emit(
            db,
            project.id,
            "node.deleted",
            {"node_ids": [str(b) for b in branches], "batch_id": str(batch), "author": author},
        )
    if experts:
        from estimator.services import team  # команда импортирует дисциплины: импорт здесь

        version = await team.remove_rows(db, principal, project, experts, via="team")
    version = await _publish_disciplines(db, principal, project.id)
    project.version = version
    return version


async def set_profile(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    discipline_id: uuid.UUID,
    profile_id: uuid.UUID,
) -> dict[str, Any]:
    """Сменить профиль ветки (одна на все фазы, FR-TREE-04); тело ``ProjectDiscipline``."""
    row = await db.get(ProjectDiscipline, (project.id, discipline_id))
    if row is None:
        raise ApiError("NOT_FOUND")
    profile = await db.get(DisciplineProfile, profile_id)
    if profile is None or profile.discipline_id != discipline_id:
        raise _validation("/profile_id", "Профиль не относится к этой дисциплине")
    if row.profile_id != profile_id:
        old = await db.get(DisciplineProfile, row.profile_id)
        row.profile_id = profile_id
        row.updated_by = principal.user_id
        await db.flush()
        journal.record(
            db,
            project.id,
            principal.user_id,
            "project.branch_profile",
            {
                "discipline_id": (str(discipline_id), str(discipline_id)),
                "profile": (old.name if old else None, profile.name),
            },
        )
        project.version = await _publish_disciplines(db, principal, project.id)
    discipline = await db.get(Discipline, discipline_id)
    has_expert = await db.scalar(
        select(func.count()).where(
            ProjectMember.project_id == project.id,
            ProjectMember.role == ProjectRole.EXPERT,
            ProjectMember.discipline_id == discipline_id,
        )
    )
    return {
        "discipline_id": str(discipline_id),
        "name": discipline.name if discipline else "",
        "profile_id": str(profile_id),
        "has_expert": bool(has_expert),
    }
