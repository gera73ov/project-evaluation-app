"""События аудита категории «Безопасность» с защитой журнала от потока (SEC-010).

SEC-AUD-01 («Безопасность»), SEC-AUTHZ-03, FR-SA-06, SEC-WEB-07. Отказы приходят сериями (перебор
идентификаторов, скрипт, повторы клиента), а журнал — хэш-цепочка, которую нельзя чистить. Поэтому
каждое событие пишется не чаще раза в минуту на свой ключ:

* :func:`access_denied` — 403/404 на объект проекта; ключ — пользователь, проект и право. Повторы
  считаются, их число уходит в ``suppressed`` следующей записи по тому же ключу;
* :func:`network_denied` — отказ по сетевому ограничению админки (404); ключ — пользователь
  (или IP без сессии) и шаблон пути;
* :func:`rate_limited` — превышение лимита частоты (429); ключ — лимит и то, по чему он считается
  (IP, пользователь, проект).

Запись идёт отдельной транзакцией на подключении запроса (:func:`audit.write_detached`): запрос
отвечает ошибкой и откатывается, событие остаётся. Сбой Redis или БД ответ пользователю не меняет.
"""

from __future__ import annotations

import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.logging import get_logger
from estimator.security import audit

log = get_logger(__name__)

WINDOW_SECONDS = 60
KEY_PREFIX = "audit:sec:"


async def _first_in_window(redis: Redis, key: str) -> int | None:
    """Первое событие по ключу за окно → число свёрнутых повторов прошлого окна; иначе ``None``."""
    full = KEY_PREFIX + key
    if await redis.set(full, "1", nx=True, ex=WINDOW_SECONDS):
        return int(await redis.getdel(full + ":n") or 0)
    await redis.incr(full + ":n")
    await redis.expire(full + ":n", WINDOW_SECONDS * 2)
    return None


async def _throttled(redis: Redis, key: str) -> int | None:
    try:
        return await _first_in_window(redis, key)
    except Exception:  # без Redis пишем каждое событие: потерять отказ хуже, чем записать лишний
        log.exception("security_audit_throttle_failed")
        return 0


async def access_denied(
    db: AsyncSession,
    redis: Redis,
    *,
    user_id: uuid.UUID,
    login: str | None,
    ip: str | None,
    session_id: str | None,
    project_id: uuid.UUID,
    status: int,
    permission: str,
    method: str,
    route: str,
) -> bool:
    """``security.access_denied``; ``True`` — событие записано, ``False`` — свёрнуто."""
    suppressed = await _throttled(redis, f"denied:{user_id}:{project_id}:{permission}")
    if suppressed is None:
        return False
    await audit.write_detached(
        db, "security.access_denied", "denied",
        user_id=user_id, login=login, ip=ip, session_id=session_id,
        object_type="project", object_id=project_id, project_id=project_id,
        details={"status": status, "permission": permission, "method": method, "route": route,
                 "suppressed": suppressed},
    )  # fmt: skip
    return True


async def network_denied(
    db: AsyncSession,
    redis: Redis,
    *,
    user_id: uuid.UUID | None,
    login: str | None,
    ip: str | None,
    session_id: str | None,
    route: str,
) -> bool:
    """``security.network_denied``: запрос к админке не из разрешённой сети."""
    who = str(user_id) if user_id is not None else f"ip:{ip}"
    if await _throttled(redis, f"network:{who}:{route}") is None:
        return False
    await audit.write_detached(
        db, "security.network_denied", "denied",
        user_id=user_id, login=login, ip=ip, session_id=session_id, details={"route": route},
    )  # fmt: skip
    return True


async def rate_limited(
    db: AsyncSession,
    redis: Redis,
    limit: str,
    identity: str,
    retry_after: int,
    *,
    user_id: uuid.UUID | None = None,
    login: str | None = None,
    ip: str | None = None,
    session_id: str | None = None,
    project_id: uuid.UUID | None = None,
) -> bool:
    """``security.rate_limited``: ответ 429 по лимиту ``limit`` (имя из ``LIMITS``)."""
    if await _throttled(redis, f"rate:{limit}:{identity}") is None:
        return False
    extra: dict[str, Any] = {}
    if project_id is not None:
        extra = {"object_type": "project", "object_id": project_id, "project_id": project_id}
    await audit.write_detached(
        db, "security.rate_limited", "denied",
        user_id=user_id, login=login, ip=ip, session_id=session_id,
        actor="user" if user_id is not None else "anonymous",
        details={"limit": limit, "retry_after": retry_after}, **extra,
    )  # fmt: skip
    return True
