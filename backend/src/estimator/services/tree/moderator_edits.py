"""CORE-022 · правка модератором чужой ветки (SPEC FR-TREE-34, 1.1, 1.3; notifications.yaml
``moderator_change``).

Модератор проекта, который не эксперт дисциплины ветки, правит её узлы: правка сохраняется сразу,
автор в истории — модератор, «Проверено» и «готово» сбрасываются по таблице BR-BR-02 тем же путём,
что и у эксперта. Экспертам дисциплины (кроме автора) приходит ``moderator_change`` с узлом
и полями:
``title``, ``type``, ``o``, ``r``, ``p``, ``multiplier``, ``comment`` (правка), ``structure``
(добавление, удаление, восстановление, разбиение, сворачивание, дублирование), ``move`` (перенос).
Событие в ленте обсуждения листа подключит CORE-043.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.enums import ProjectRole
from estimator.db.models.projects import ProjectMember
from estimator.notifications import inapp

FIELDS = ("title", "type", "o", "r", "p", "multiplier", "comment", "structure", "move")


async def notify_experts(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    discipline_id: uuid.UUID | None,
    fields: Iterable[str],
) -> None:
    """``moderator_change`` экспертам дисциплины, если правку сделал модератор не из неё."""
    wanted = sorted({f for f in fields if f in FIELDS}, key=FIELDS.index)
    if discipline_id is None or not wanted:
        return
    members = (
        await db.execute(
            select(ProjectMember.user_id, ProjectMember.role, ProjectMember.discipline_id).where(
                ProjectMember.project_id == project_id
            )
        )
    ).all()
    mine = {(role, d) for user, role, d in members if user == principal.user_id}
    if not any(role is ProjectRole.MODERATOR for role, _ in mine):
        return  # правит эксперт (или поддержка): это не «изменение модератора»
    if (ProjectRole.EXPERT, discipline_id) in mine:
        return  # модератор — сам эксперт этой дисциплины
    experts = {
        user for user, role, d in members if role is ProjectRole.EXPERT and d == discipline_id
    }
    await inapp.notify(
        db,
        "moderator_change",
        experts,
        project_id=project_id,
        node_id=node_id,
        payload={
            "project_id": str(project_id),
            "node_id": str(node_id),
            "actor_id": str(principal.user_id),
            "fields": wanted,
        },
        actor_id=principal.user_id,
    )
