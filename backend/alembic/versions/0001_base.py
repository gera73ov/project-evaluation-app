"""Роли БД, расширение citext, схема audit, права по умолчанию.

Ревизия: 0001_base
Предыдущая: —
Задача PLAN.md: DB-002. Шаг: expand.

* Роли ``estimator_migrator``, ``estimator_app``, ``estimator_audit_purge`` (contracts/db/schema.md
  G-14) создаются ``NOLOGIN``, если их ещё нет. Роли кластерные: ``downgrade`` их не удаляет
  (ими могут пользоваться другие базы кластера, например параллельные тестовые базы).
* Схема ``audit`` принадлежит ``estimator_migrator``; у ``estimator_app`` в ней нет ``CREATE``.
* Объекты, которые migrator создаёт в ``public``, автоматически получают права DML для
  ``estimator_app`` (``ALTER DEFAULT PRIVILEGES``); таблицы «только INSERT» отзывают лишнее сами.
* В конце соединение переключается на ``estimator_migrator`` — следующие ревизии того же прогона
  создают объекты от её имени (в следующих прогонах это делает alembic/env.py).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Параллельные прогоны на одном кластере (pytest-xdist) могут создавать роль одновременно,
# поэтому дубль роли не ошибка.
CREATE_ROLES = """
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['estimator_migrator', 'estimator_app', 'estimator_audit_purge'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      BEGIN
        EXECUTE format('CREATE ROLE %I NOLOGIN', r);
      EXCEPTION WHEN duplicate_object OR unique_violation THEN
        NULL;
      END;
    END IF;
  END LOOP;
END
$$;
"""

UPGRADE = [
    # Пользователь соединения (владелец базы или суперпользователь) должен уметь стать migrator
    "GRANT estimator_migrator TO SESSION_USER",
    "CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public",
    # public: создавать объекты может только migrator; остальные — только использовать
    "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
    "GRANT USAGE, CREATE ON SCHEMA public TO estimator_migrator",
    "GRANT USAGE ON SCHEMA public TO estimator_app, estimator_audit_purge",
    # Таблица версий Alembic создана до этой ревизии от имени текущего пользователя
    "GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version TO estimator_migrator",
    # Схема журнала аудита (SEC-AUD-03): владелец migrator, приложению — только USAGE
    "CREATE SCHEMA audit AUTHORIZATION estimator_migrator",
    "REVOKE ALL ON SCHEMA audit FROM PUBLIC",
    "GRANT USAGE ON SCHEMA audit TO estimator_app, estimator_audit_purge",
    # Права по умолчанию на объекты migrator в public
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO estimator_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator IN SCHEMA public "
    "GRANT USAGE, SELECT ON SEQUENCES TO estimator_app",
    # Функции по умолчанию доступны PUBLIC — у migrator отзываем, выдаём явно
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    "SET ROLE estimator_migrator",
]

DOWNGRADE = [
    "RESET ROLE",
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator IN SCHEMA public "
    "REVOKE USAGE, SELECT ON SEQUENCES FROM estimator_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE estimator_migrator IN SCHEMA public "
    "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM estimator_app",
    "DROP SCHEMA audit",
    # Права migrator на alembic_version остаются: повторный `upgrade` идёт от migrator (env.py)
    "REVOKE ALL ON SCHEMA public FROM estimator_app, estimator_audit_purge, estimator_migrator",
    "GRANT CREATE ON SCHEMA public TO PUBLIC",
    "DROP EXTENSION IF EXISTS citext",
]


def upgrade() -> None:
    # DDL уровня базы (расширение, схема, права на public) — от пользователя соединения
    run(["RESET ROLE", CREATE_ROLES, *UPGRADE])


def downgrade() -> None:
    run(DOWNGRADE)


def run(statements: list[str]) -> None:
    # Операторы — константы модуля; exec_driver_sql не разбирает «:имя» как параметры
    # (двоеточия в PL/pgSQL и форматах to_char — часть SQL). Правило — alembic/README.md.
    conn = op.get_bind()
    for statement in statements:
        conn.exec_driver_sql(statement)
