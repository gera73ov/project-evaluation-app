"""Дерево оценки, история узлов, лог изменений, состояние вида, журнал проекта.

Ревизия: 0007_tree
Предыдущая: 0006_projects
Задача PLAN.md: DB-006. Шаг: expand.

contracts/db/schema.md 2.4 (``nodes``, ``node_history``, ``change_log``, ``user_view_state``) и 3
(``project_journal``: таблица сверх 14.2 для CORE-032, миграции пишет только трек DB).
Индексы — SPEC 14.3. ``node_history`` и ``project_journal`` — только INSERT для
``estimator_app`` (G-5): права ``UPDATE``/``DELETE`` отзываются у роли, которой их выдали права
по умолчанию (0001_base).
Каскадные удаления (корзина, ``estimator project purge``) выполняются от имени владельца таблицы,
поэтому отзыв прав им не мешает.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_tree"
down_revision: str | None = "0006_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT = """
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by uuid"""


def audit_fk(table: str) -> str:
    return (
        f"CONSTRAINT {table}_created_by_fkey FOREIGN KEY (created_by) "
        f"REFERENCES users (id) ON DELETE RESTRICT,\n"
        f"        CONSTRAINT {table}_updated_by_fkey FOREIGN KEY (updated_by) "
        f"REFERENCES users (id) ON DELETE RESTRICT"
    )


def project_fk(table: str) -> str:
    return (
        f"CONSTRAINT {table}_project_id_fkey FOREIGN KEY (project_id) "
        f"REFERENCES projects (id) ON DELETE CASCADE"
    )


def user_fk(table: str, column: str) -> str:
    return (
        f"CONSTRAINT {table}_{column}_fkey FOREIGN KEY ({column}) "
        f"REFERENCES users (id) ON DELETE RESTRICT"
    )


def hours_check(column: str) -> str:
    # BR-CALC-03: 0–99 999,5 с шагом 0,5
    return (
        f"CONSTRAINT nodes_{column}_check CHECK ({column} IS NULL OR "
        f"({column} BETWEEN 0 AND 99999.5 AND {column} * 2 = trunc({column} * 2)))"
    )


UPGRADE = [
    "CREATE TYPE node_kind AS ENUM ('phase', 'discipline', 'item')",
    "CREATE TYPE node_action AS ENUM "
    "('create', 'update', 'move', 'delete', 'restore', 'split', 'collapse', 'review')",
    f"""
    CREATE TABLE nodes (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        parent_id uuid,
        kind node_kind NOT NULL,
        phase_id uuid NOT NULL,
        discipline_id uuid,
        type_id uuid,
        title varchar(200) NOT NULL,
        position text COLLATE "C" NOT NULL,
        o numeric(10, 2),
        r numeric(10, 2),
        p numeric(10, 2),
        multiplier integer NOT NULL DEFAULT 1,
        comment_lines jsonb,
        reviewed_by uuid,
        reviewed_at timestamptz,
        self_review boolean NOT NULL DEFAULT false,
        version integer NOT NULL DEFAULT 1,
        field_versions jsonb NOT NULL DEFAULT '{{}}',
        deleted_at timestamptz,
        deleted_batch_id uuid,
        deleted_by uuid,{AUDIT},
        CONSTRAINT nodes_pkey PRIMARY KEY (id),
        {project_fk("nodes")},
        CONSTRAINT nodes_parent_id_fkey FOREIGN KEY (parent_id)
            REFERENCES nodes (id) ON DELETE CASCADE,
        CONSTRAINT nodes_phase_id_fkey FOREIGN KEY (phase_id)
            REFERENCES phases (id) ON DELETE RESTRICT,
        CONSTRAINT nodes_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT nodes_type_id_fkey FOREIGN KEY (type_id) REFERENCES node_types (id),
        {user_fk("nodes", "reviewed_by")},
        {user_fk("nodes", "deleted_by")},
        CONSTRAINT nodes_title_check
            CHECK (char_length(title) >= 1 AND title !~ '[\\r\\n]'),
        {hours_check("o")},
        {hours_check("r")},
        {hours_check("p")},
        CONSTRAINT nodes_multiplier_check CHECK (multiplier BETWEEN 1 AND 10000),
        CONSTRAINT nodes_comment_lines_check
            CHECK (comment_lines IS NULL OR jsonb_typeof(comment_lines) = 'array'),
        CONSTRAINT nodes_reviewed_check CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL)),
        CONSTRAINT nodes_self_review_check CHECK (NOT self_review OR reviewed_by IS NOT NULL),
        CONSTRAINT nodes_deleted_check
            CHECK ((deleted_at IS NULL) = (deleted_batch_id IS NULL)),
        CONSTRAINT nodes_item_branch_check
            CHECK (kind <> 'item' OR (phase_id IS NOT NULL AND discipline_id IS NOT NULL)),
        CONSTRAINT nodes_root_check CHECK ((kind = 'phase') = (parent_id IS NULL)),
        CONSTRAINT nodes_phase_kind_check CHECK (kind <> 'phase' OR (discipline_id IS NULL
            AND o IS NULL AND r IS NULL AND p IS NULL)),
        CONSTRAINT nodes_discipline_kind_check
            CHECK (kind <> 'discipline' OR discipline_id IS NOT NULL),
        CONSTRAINT nodes_type_check CHECK (kind = 'item' OR type_id IS NULL),
        {audit_fk("nodes")}
    )
    """,
    # SPEC 14.3: загрузка дерева и порядок соседей
    "CREATE INDEX nodes_project_live_idx ON nodes (project_id) WHERE deleted_at IS NULL",
    "CREATE INDEX nodes_parent_position_idx ON nodes (parent_id, position)",
    "CREATE INDEX nodes_batch_idx ON nodes (project_id, deleted_batch_id) "
    "WHERE deleted_at IS NOT NULL",
    "CREATE UNIQUE INDEX nodes_one_phase ON nodes (project_id, phase_id) "
    "WHERE kind = 'phase' AND deleted_at IS NULL",
    "CREATE UNIQUE INDEX nodes_one_branch ON nodes (project_id, phase_id, discipline_id) "
    "WHERE kind = 'discipline' AND deleted_at IS NULL",
    f"""
    CREATE TABLE node_history (
        id uuid NOT NULL,
        node_id uuid NOT NULL,
        project_id uuid NOT NULL,
        project_version bigint NOT NULL,
        node_version integer NOT NULL,
        user_id uuid,
        action node_action NOT NULL,
        changes jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT node_history_pkey PRIMARY KEY (id),
        CONSTRAINT node_history_node_id_fkey FOREIGN KEY (node_id)
            REFERENCES nodes (id) ON DELETE CASCADE,
        {project_fk("node_history")},
        {user_fk("node_history", "user_id")}
    )
    """,
    "CREATE INDEX node_history_node_id_created_at_idx ON node_history (node_id, created_at)",
    "CREATE INDEX node_history_project_id_user_id_created_at_idx "
    "ON node_history (project_id, user_id, created_at)",
    f"""
    CREATE TABLE change_log (
        project_id uuid NOT NULL,
        version bigint NOT NULL,
        event jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT change_log_pkey PRIMARY KEY (project_id, version),
        {project_fk("change_log")}
    )
    """,
    "CREATE INDEX change_log_created_at_idx ON change_log (created_at)",
    f"""
    CREATE TABLE user_view_state (
        user_id uuid NOT NULL,
        project_id uuid NOT NULL,
        state jsonb NOT NULL DEFAULT '{{}}',
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT user_view_state_pkey PRIMARY KEY (user_id, project_id),
        {user_fk("user_view_state", "user_id")},
        {project_fk("user_view_state")}
    )
    """,
    "CREATE INDEX user_view_state_project_id_idx ON user_view_state (project_id)",
    f"""
    CREATE TABLE project_journal (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        user_id uuid,
        action text NOT NULL,
        is_money boolean NOT NULL DEFAULT false,
        changes jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT project_journal_pkey PRIMARY KEY (id),
        {project_fk("project_journal")},
        {user_fk("project_journal", "user_id")},
        CONSTRAINT project_journal_money_keys_check CHECK (is_money OR NOT (changes ?| array[
            'rate_rub', 'exchange_rate', 'vat_percent', 'contract_amount', 'currency']))
    )
    """,
    "CREATE INDEX project_journal_project_id_id_idx ON project_journal (project_id, id DESC)",
    # G-5: только INSERT (и чтение) для роли приложения
    "REVOKE UPDATE, DELETE, TRUNCATE ON node_history, project_journal FROM estimator_app",
]

DOWNGRADE = [
    "DROP TABLE project_journal",
    "DROP TABLE user_view_state",
    "DROP TABLE change_log",
    "DROP TABLE node_history",
    "DROP TABLE nodes",
    "DROP TYPE node_action",
    "DROP TYPE node_kind",
]


def upgrade() -> None:
    run(UPGRADE)


def downgrade() -> None:
    run(DOWNGRADE)


def run(statements: list[str]) -> None:
    # Операторы — константы модуля; exec_driver_sql не разбирает «:имя» как параметры
    # (двоеточия в PL/pgSQL и форматах to_char — часть SQL). Правило — alembic/README.md.
    conn = op.get_bind()
    for statement in statements:
        conn.exec_driver_sql(statement)
