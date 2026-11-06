"""RT-002 · интерфейс захватов ячеек для ядра до RT-005 (FR-TREE-31, TC-CONC-04).

Ядро перед записью поля узла вызывает::

    await assert_not_locked(project_id, node_id, "r", user_id=principal.user_id)

Если поле захвачено другим пользователем, реализация бросает 423 ``CELL_LOCKED`` с
``locked_by`` и ``expires_at`` (contracts/errors.yaml). До RT-005 стоит :class:`NoLocks`:
захватов нет, проверка всегда проходит. RT-005 подключит реализацию на Redis
(``lock:{project_id}:{node_id}:{field}``, TTL 30 с) через :func:`set_lock_checker`, и вызовы ядра
менять не придётся.
"""

from __future__ import annotations

import uuid
from typing import Literal, Protocol

#: Захватываемые ячейки (contracts/ws-events.md, толкование 1; ``$defs.LockField``)
LockField = Literal["title", "multiplier", "comment", "o", "r", "p"]
LOCK_FIELDS: frozenset[str] = frozenset({"title", "multiplier", "comment", "o", "r", "p"})


class LockChecker(Protocol):
    async def assert_not_locked(
        self, project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, user_id: uuid.UUID
    ) -> None: ...


class NoLocks:
    """Заглушка до RT-005: никаких захватов нет."""

    async def assert_not_locked(
        self, project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, user_id: uuid.UUID
    ) -> None:
        return None


_checker: LockChecker = NoLocks()


def set_lock_checker(checker: LockChecker) -> LockChecker:
    """Подключить реализацию захватов; возвращает прежнюю."""
    global _checker
    previous, _checker = _checker, checker
    return previous


async def assert_not_locked(
    project_id: uuid.UUID, node_id: uuid.UUID, field: str, *, user_id: uuid.UUID
) -> None:
    """Поле не захвачено другим пользователем; иначе 423 ``CELL_LOCKED`` (после RT-005)."""
    if field not in LOCK_FIELDS:
        raise ValueError(f"поле {field!r} не захватывается (допустимы {sorted(LOCK_FIELDS)})")
    await _checker.assert_not_locked(project_id, node_id, field, user_id=user_id)
