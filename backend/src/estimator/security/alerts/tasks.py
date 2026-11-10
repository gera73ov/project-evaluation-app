"""Задачи Celery оповещений ИБ (SEC-011).

``notify_alert`` собирает получателей по БД и ставит письма; ``record_undelivered`` вызывает
задача письма, когда оповещение не ушло окончательно. Обе открывают своё подключение к БД и Redis:
в worker нет запроса и его сессии.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from celery import shared_task

from estimator.logging import get_logger

log = get_logger(__name__)


async def _with_db(work: Callable[[Any, Any], Awaitable[Any]]) -> Any:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.config import get_settings
    from estimator.db.session import create_engine, transaction

    settings = get_settings()
    engine = create_engine(settings)
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        async with transaction(async_sessionmaker(engine, expire_on_commit=False)) as db:
            return await work(db, redis)
    finally:
        await redis.aclose()
        await engine.dispose()


@shared_task(name="estimator.security.alert")
def notify_alert(
    key: str, time: str, actor_login: str | None, ip: str | None, channel: str | None = None
) -> int:
    from estimator.security.alerts import notify

    async def work(db: Any, _redis: Any) -> int:
        return await notify.dispatch(
            db, key, time=time, actor_login=actor_login, ip=ip, channel=channel
        )

    return int(asyncio.run(_with_db(work)))


def publish(
    key: str, time: str, actor_login: str | None, ip: str | None, channel: str | None
) -> None:
    """Поставить рассылку в очередь без повторов публикации: брокер недоступен — сразу ошибка
    (её пишет в лог слушатель аудита), запрос пользователя не ждёт."""
    notify_alert.apply_async((key, time, actor_login, ip, channel), retry=False)


def record_undelivered(alert_type: str, channel: str) -> None:
    """Из задачи письма (синхронно): отметить недоставленное оповещение; сбой — только в лог."""
    from estimator.security.alerts import notify

    async def work(db: Any, redis: Any) -> None:
        await notify.record_undelivered(db, redis, alert_type, channel)

    try:
        asyncio.run(_with_db(work))
    except Exception:
        log.exception("security_alert_undelivered_record_failed", alert=alert_type)
