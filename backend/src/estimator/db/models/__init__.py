"""ORM-модели (трек DB, PLAN.md раздел 5; contracts/db/schema.md).

Импорт пакета регистрирует все таблицы в :data:`metadata` — его используют Alembic (``alembic
check``) и тест сравнения моделей со схемой после миграций. Денежные модели (DB-005) живут в
``estimator.db.models.money`` и сюда не реэкспортируются (G-11).
"""

from __future__ import annotations

from estimator.db.base import Base
from estimator.db.models import audit, settings, users

metadata = Base.metadata

__all__ = ["audit", "metadata", "settings", "users"]
