"""Общие помощники фабрик: счётчики и детерминированные UUID."""

from __future__ import annotations

import itertools
import uuid

#: Пространство имён UUID тестовых данных: одинаковое имя → одинаковый UUID в любом прогоне.
NAMESPACE = uuid.UUID("6f1c3b0e-5d2a-4c1e-9b7f-000000000017")


def stable_uuid(*parts: str) -> uuid.UUID:
    """UUID из имени объекта, например ``stable_uuid("user", "i.ivanov")``."""
    return uuid.uuid5(NAMESPACE, "/".join(parts))


class Sequence:
    """Счётчик для уникальных значений: ``seq = Sequence("user{}")``; ``next(seq)`` → ``user1``."""

    def __init__(self, template: str = "{}") -> None:
        self._template = template
        self._counter = itertools.count(1)

    def __next__(self) -> str:
        return self._template.format(next(self._counter))

    def __iter__(self) -> Sequence:
        return self
