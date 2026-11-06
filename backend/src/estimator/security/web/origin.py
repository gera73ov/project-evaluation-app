"""Проверка ``Origin`` (SEC-007; SEC-WEB-04): WebSocket при подключении (RT-001) и, при желании,
изменяющие REST-запросы. Разрешён только собственный адрес приложения.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit


def origin_allowed(origin: str | None, allowed_hosts: Iterable[str]) -> bool:
    """``Origin`` — ``https://<разрешённый хост>``; отсутствие заголовка — отказ."""
    if not origin:
        return False
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/"):
        return False
    host = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
    return any(host == h.lower() or parts.hostname.lower() == h.lower() for h in allowed_hosts)
