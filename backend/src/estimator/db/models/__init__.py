"""ORM-модели (трек DB, PLAN.md раздел 5; contracts/db/schema.md).

Импорт пакета регистрирует все таблицы в :data:`metadata` — его используют Alembic (``alembic
check``) и тест сравнения моделей со схемой после миграций. Денежные модели (DB-005) живут в
``estimator.db.models.money``: пакет импортирует модуль только ради метаданных и наружу его
не реэкспортирует (G-11).
"""

from __future__ import annotations

from estimator.db.base import Base
from estimator.db.models import (
    audit,
    dictionaries,
    discussions,
    files,
    projects,
    settings,
    tree,
    users,
)
from estimator.db.models import money as _money  # noqa: F401 — только для metadata

metadata = Base.metadata

__all__ = [
    "audit",
    "dictionaries",
    "discussions",
    "files",
    "metadata",
    "projects",
    "settings",
    "tree",
    "users",
]
