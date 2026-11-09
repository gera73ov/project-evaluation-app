"""Общие шаги API-тестов CORE: проект через API, дисциплины справочника, аудит."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import Discipline
from tests.integration.core.conftest import Actor, World


async def create_project(world: World, moderator: Actor, *phases: str) -> uuid.UUID:
    names = phases or ("Разработка", "Тестирование")
    ids = await world.phases()
    response = await moderator.post(
        "/projects",
        json={
            "name": "Портал дилеров",
            "customer": "ООО Ромашка",
            "phase_ids": [str(ids[n]) for n in names],
        },
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["project"]["id"])


async def discipline(db: AsyncSession, name: str) -> uuid.UUID:
    return (await db.scalars(select(Discipline.id).where(Discipline.name == name))).one()


async def audit_details(
    db: AsyncSession, event: str, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = :e "
            "AND details->>'project_id' = :p ORDER BY id"
        ),
        {"e": event, "p": str(project_id)},
    )
    return [r[0] for r in rows.all()]
