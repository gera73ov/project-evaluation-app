"""Сети админки суперадминистратора (FR-SA-06, ``security.admin_networks``).

Здесь — только проверка адреса по списку CIDR; её использует движок прав (SEC-005) для прав с
флагом ``network``. Вход суперадминистраторов и WS-подключения ограничивает SEC-013.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

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
