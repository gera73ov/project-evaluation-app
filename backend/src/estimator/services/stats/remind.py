"""CORE-053 · «Напомнить не начавшим» (SPEC 10.1 «Сетка готовности», 11.8 №7, FR-NOTIF-03;
15.2 ``POST /projects/{id}/remind``; notifications.yaml ``remind_not_started``).

Письмо получают эксперты дисциплин, у которых хотя бы одна ветка включённой фазы работ в статусе
«не начато». В письме — название проекта, дедлайн и ссылка, без названий узлов (FR-NOTIF-03).
Не чаще раза в сутки на проект: ключ Redis ставится только при успешной отправке, повтор — 429
``REMIND_TOO_OFTEN`` с ``Retry-After``. Без адресатов письмо не уходит и сутки не начинаются
(``sent_to: 0``); интерфейс видит адресатов по сетке готовности (ячейки «не начато» без флажка
``no_expert``).
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.passwords import base_url
from estimator.db.enums import BranchStatusValue, ProjectRole
from estimator.db.models.projects import BranchStatus, Project, ProjectMember
from estimator.db.models.users import User
from estimator.notifications.mail.recipients import Recipient
from estimator.notifications.tasks import enqueue_email
from estimator.services.tree.load import project_disciplines, project_phases

KEY = "remind:not_started:"
PERIOD_SECONDS = 24 * 3600
KIND = "remind_not_started"


async def _not_started_disciplines(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    phases = [p.phase_id for p in await project_phases(db, project_id)
              if p.is_enabled and not p.is_cross_cutting]  # fmt: skip
    disciplines = [d.discipline_id for d in await project_disciplines(db, project_id)]
    rows = await db.execute(
        select(BranchStatus.phase_id, BranchStatus.discipline_id, BranchStatus.status).where(
            BranchStatus.project_id == project_id
        )
    )
    status = {(ph, d): BranchStatusValue(str(s)) for ph, d, s in rows.all()}
    return {
        d
        for d in disciplines
        for ph in phases
        if status.get((ph, d), BranchStatusValue.NOT_STARTED) is BranchStatusValue.NOT_STARTED
    }


async def remind(
    db: AsyncSession, redis: Redis, principal: Principal, project: Project
) -> dict[str, int]:
    key = f"{KEY}{project.id}"
    ttl = await redis.ttl(key)
    if ttl and ttl > 0:
        raise ApiError("REMIND_TOO_OFTEN", headers={"Retry-After": str(ttl)}, retry_after=ttl)
    wanted = await _not_started_disciplines(db, project.id)
    if not wanted:
        return {"sent_to": 0}
    rows = await db.execute(
        select(User.email, User.status)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.role == ProjectRole.EXPERT,
            ProjectMember.discipline_id.in_(wanted),
            User.id != principal.user_id,
        )
        .distinct()
    )
    recipients = [Recipient(email, str(status)) for email, status in rows.all()]
    if not recipients:
        return {"sent_to": 0}
    if not await redis.set(key, "1", nx=True, ex=PERIOD_SECONDS):
        raise ApiError(
            "REMIND_TOO_OFTEN",
            headers={"Retry-After": str(PERIOD_SECONDS)},
            retry_after=PERIOD_SECONDS,
        )
    fields = {
        "project_name": project.name,
        "deadline": None if project.deadline is None else project.deadline.strftime("%d.%m.%Y"),
        "link": f"{await base_url(db)}/projects/{project.id}",
    }
    return {"sent_to": enqueue_email(KIND, recipients, fields)}
