"""Ссылка на пользователя в событиях WebSocket (``$defs.UserRef`` контракта RT-001).

Цвет — DESIGN.md 2.6: ``palette[hash(user_id) % 10]``, одинаковый у всех зрителей; хэш —
целое значение UUID. Заблокированный пользователь — ``--muted``. Инициалы — первые буквы
фамилии и имени из «Фамилия Имя Отчество», как у аватара фронтенда (``AppShell.initials``).
"""

from __future__ import annotations

import uuid
from typing import Any

PALETTE = (
    "#557a9a",
    "#a8661e",
    "#5e7f4f",
    "#437f7f",
    "#9c6a2e",
    "#7f62a6",
    "#9a5a8a",
    "#7a6a5a",
    "#a0605a",
    "#8a5a44",
)
MUTED = "#66717d"


def user_color(user_id: uuid.UUID, *, active: bool = True) -> str:
    return PALETTE[user_id.int % len(PALETTE)] if active else MUTED


def initials(full_name: str) -> str:
    parts = full_name.split()
    last = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else ""
    return (last[:1] + first[:1]).upper()


def user_ref(user_id: uuid.UUID, full_name: str, *, active: bool = True) -> dict[str, Any]:
    return {
        "id": str(user_id),
        "full_name": full_name[:200],
        "initials": initials(full_name),
        "is_active": active,
        "color": user_color(user_id, active=active),
    }
