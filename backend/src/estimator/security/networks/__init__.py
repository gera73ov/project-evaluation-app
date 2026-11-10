"""Сети админки суперадминистратора (FR-SA-06, ``security.admin_networks``).

Проверка адреса по списку CIDR: её использует движок прав (SEC-005) для прав с флагом ``network``
(``/api/v1/system/*``), рукопожатие WebSocket для сессий суперадминистратора и
:func:`guard_superadmin_login` — для входа суперадминистратора ``/api/v1/auth/*`` (SEC-013).
Реальный IP за Nginx берётся из ``X-Forwarded-For`` только от доверенных прокси (Uvicorn
``forwarded_allow_ips``, INF-009). Изменение списка оповещает ИБ (SEC-011).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.auth.policy import read_settings

SETTING = "security.admin_networks"


def address_allowed(ip: str, networks: Iterable[str]) -> bool:
    """Пустой список — без ограничения; неразборчивый адрес при заданном списке — запрет."""
    nets = [ipaddress.ip_network(n, strict=False) for n in networks]
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == net.version and addr in net for net in nets)


async def load_admin_networks(conn: AsyncConnection | AsyncSession) -> list[str]:
    values = await read_settings(conn, SETTING)
    return list(values.get(SETTING) or [])


async def guard_superadmin_login(
    db: AsyncSession,
    redis: Redis,
    *,
    ip: str,
    route: str,
    user_id: UUID | None = None,
    login: str | None = None,
    session_id: str | None = None,
) -> None:
    """Вход суперадминистратора не из разрешённой сети — 404 (FR-SA-06, SEC-013).

    Вызывается только для зарезервированных логинов (FR-AUTH-AD-12) и сессий суперадминистратора
    на маршрутах ``/api/v1/auth/*``. Отказ пишется в аудит не чаще раза в минуту на ключ (SEC-010).
    """
    if address_allowed(ip, await load_admin_networks(db)):
        return
    from estimator.api.common.errors import ApiError
    from estimator.security.audit import security_events

    await security_events.network_denied(
        db, redis, user_id=user_id, login=login, ip=ip, session_id=session_id, route=route
    )
    raise ApiError("NOT_FOUND")
