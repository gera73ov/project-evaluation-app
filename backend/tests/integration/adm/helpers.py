"""Общие помощники API-тестов ADM: аудит, step-up."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.core.conftest import Actor, World


async def audit_details(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"), {"e": event}
    )
    return [r[0] for r in rows.all()]


async def step_up(world: World, actor: Actor) -> None:
    """Пройденный step-up на 5 минут (SEC-AUTH-05) без ввода пароля и TOTP."""
    loaded: Any = await world.service.load(actor.sid)
    await world.service.update(
        world.db, actor.sid, loaded.record, step_up_until=world.service.now() + 300
    )
