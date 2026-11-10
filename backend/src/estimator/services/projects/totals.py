"""CORE-026 · кэш итогов проекта ``project_totals`` (SPEC ARCH-03, FR-HOME-04, BR-MONEY-04, 14.2).

Любое изменение, которое поднимает версию проекта (дерево, настройки, фазы, статусы веток), и
правка денег вызывают :func:`schedule`. После commit хук ставит фоновую задачу пересчёта с
задержкой :data:`DEBOUNCE_SECONDS`; ключ Redis ``SET NX`` на время задержки склеивает серию правок
в один пересчёт (дебаунс). Задача снимает ключ до расчёта, так что правка во время расчёта
поставит следующий. Итог появляется в кэше не позже чем через ~10 с после правки.

Сам расчёт и запись строки — :func:`estimator.services.money.totals.refresh` (модели денег
доступны только сервису денег, G-11). Значение, не помещающееся в столбец, не пишется (``NULL``,
в списке «—»): задача от переполнения не падает.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.session import after_commit
from estimator.logging import get_logger

TOTALS_TASK = "estimator.projects.totals"
DEBOUNCE_SECONDS = 5
_KEY = "totals:pending:{}"

log = get_logger(__name__)


async def _enqueue(project_id: uuid.UUID) -> None:  # pragma: no cover — нужен брокер Celery
    from redis.asyncio import Redis

    from estimator.config import get_settings

    redis = Redis.from_url(get_settings().redis_url.get_secret_value())
    try:
        fresh = await redis.set(_KEY.format(project_id), b"1", nx=True, ex=DEBOUNCE_SECONDS * 2)
    finally:
        await redis.aclose()
    if fresh:
        recompute_totals.apply_async((str(project_id),), countdown=DEBOUNCE_SECONDS)


#: Постановка пересчёта; тесты подменяют её записью вызовов.
enqueue: Callable[[uuid.UUID], Awaitable[None]] = _enqueue


def schedule(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Пересчитать кэш итогов проекта после commit текущей транзакции."""

    async def hook() -> None:
        try:
            await enqueue(project_id)
        except Exception as exc:  # noqa: BLE001 — сбой постановки не должен ронять запрос
            log.warning(
                "totals_enqueue_failed", project_id=str(project_id), error=type(exc).__name__
            )

    after_commit(db, hook)


async def recompute(db: AsyncSession, project_id: uuid.UUID) -> bool:
    """Пересчитать и записать кэш итогов; ``False`` — проекта нет."""
    from estimator.db.models.projects import Project
    from estimator.services.money import totals

    project = await db.get(Project, project_id)
    if project is None:
        return False
    await totals.refresh(db, project)
    return True


async def _run(project_id: uuid.UUID) -> bool:  # pragma: no cover — запуск в worker
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.config import get_settings
    from estimator.db.session import create_engine

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        await redis.delete(_KEY.format(project_id))
    finally:
        await redis.aclose()
    engine = create_engine(settings)  # свой движок: у asyncio.run свой цикл событий
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return await recompute(db, project_id)
    finally:
        await engine.dispose()


@shared_task(name=TOTALS_TASK)
def recompute_totals(project_id: str) -> bool:  # pragma: no cover — запуск в worker
    return asyncio.run(_run(uuid.UUID(project_id)))
