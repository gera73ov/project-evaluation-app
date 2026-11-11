"""Индексы ключевых запросов по итогам EXPLAIN.

Ревизия: 0010_query_indexes
Предыдущая: 0009_snapshots_files
Задача PLAN.md: DB-013. Шаг: expand.

Лента обсуждений проекта (``GET /projects/{id}/threads``) выбирает все треды проекта, новые
сверху: частичный индекс ``threads_project_open_idx`` подходит только открытым, и запрос шёл
последовательным сканом ``threads``. Проверка — ``tests/perf/test_query_plans.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_query_indexes"
down_revision: str | None = "0009_snapshots_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = [
    "CREATE INDEX threads_project_created_idx ON threads (project_id, created_at DESC, id DESC)",
]

DOWNGRADE = [
    "DROP INDEX threads_project_created_idx",
]


def upgrade() -> None:
    run(UPGRADE)


def downgrade() -> None:
    run(DOWNGRADE)


def run(statements: list[str]) -> None:
    # Операторы — константы модуля (alembic/README.md)
    conn = op.get_bind()
    for statement in statements:
        conn.exec_driver_sql(statement)
