"""Режим «Приложение настраивается» (AUTH-012; FR-SA-02, раздел 7.1).

Пока мастер первичной настройки не завершён (``app.setup.completed_at`` пуст), входить может
только суперадминистратор; остальным вход и любые API отвечают 503 ``APP_SETUP_IN_PROGRESS``.
Фронтенд по этому коду показывает страницу-заглушку. Ключ ``app.setup`` ведёт мастер (ADM-001).
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.auth.policy import read_settings

SETUP_KEY = "app.setup"
SETUP_IN_PROGRESS = "APP_SETUP_IN_PROGRESS"


class SetupInProgressError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=503, detail={"code": SETUP_IN_PROGRESS})


async def setup_completed(conn: AsyncConnection | AsyncSession) -> bool:
    value = (await read_settings(conn, SETUP_KEY)).get(SETUP_KEY) or {}
    return bool(value.get("completed_at"))


async def ensure_setup_allows(conn: AsyncConnection | AsyncSession, *, superadmin: bool) -> None:
    """Пропустить суперадминистратора всегда, остальных — только после мастера."""
    if superadmin:
        return
    if not await setup_completed(conn):
        raise SetupInProgressError
