"""Обсуждения, вопросы заказчику, адресаты, заметки модераторов, уведомления.

Ревизия: 0008_discussions
Предыдущая: 0007_tree
Задача PLAN.md: DB-007. Шаг: expand.

contracts/db/schema.md 2.5 (кроме ``customer_documents`` — DB-008). Индексы — SPEC 14.3;
номер вопроса заказчику уникален в проекте (FR-CQ-02). ``message_history`` — только INSERT для
``estimator_app`` (G-5). ``project_notes`` — [А] (G-4) плюс ``author_id`` и ``edited_at`` из 2.5.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_discussions"
down_revision: str | None = "0007_tree"
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


def node_fk(table: str, on_delete: str = "CASCADE") -> str:
    return (
        f"CONSTRAINT {table}_node_id_fkey FOREIGN KEY (node_id) "
        f"REFERENCES nodes (id) ON DELETE {on_delete}"
    )


def user_fk(table: str, column: str) -> str:
    return (
        f"CONSTRAINT {table}_{column}_fkey FOREIGN KEY ({column}) "
        f"REFERENCES users (id) ON DELETE RESTRICT"
    )


UPGRADE = [
    "CREATE TYPE thread_status AS ENUM ('open', 'resolved')",
    "CREATE TYPE customer_question_status AS ENUM "
    "('new', 'sent', 'answered', 'closed', 'withdrawn')",
    "CREATE TYPE message_kind AS ENUM ('message', 'event', 'customer_answer')",
    "CREATE TYPE message_history_reason AS ENUM ('edit', 'revoke', 'edit_after_sent')",
    "CREATE TYPE addressee_type AS ENUM ('user', 'discipline', 'moderators', 'customer')",
    f"""
    CREATE TABLE threads (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        node_id uuid,
        opened_by uuid NOT NULL,
        status thread_status NOT NULL DEFAULT 'open',
        resolved_by uuid,
        resolved_at timestamptz,
        is_customer boolean NOT NULL DEFAULT false,
        customer_question_no integer,
        customer_status customer_question_status,
        sent_at timestamptz,
        answered_at timestamptz,
        closed_by uuid,
        closed_at timestamptz,
        withdraw_reason varchar(500),
        edited_after_sent boolean NOT NULL DEFAULT false,{AUDIT},
        CONSTRAINT threads_pkey PRIMARY KEY (id),
        {project_fk("threads")},
        {node_fk("threads")},
        {user_fk("threads", "opened_by")},
        {user_fk("threads", "resolved_by")},
        {user_fk("threads", "closed_by")},
        CONSTRAINT threads_customer_question_no_check
            CHECK (is_customer = (customer_question_no IS NOT NULL)),
        CONSTRAINT threads_customer_status_check
            CHECK (is_customer = (customer_status IS NOT NULL)),
        CONSTRAINT threads_withdraw_reason_check
            CHECK (customer_status IS DISTINCT FROM 'withdrawn' OR withdraw_reason IS NOT NULL),
        {audit_fk("threads")}
    )
    """,
    "CREATE INDEX threads_project_open_idx ON threads (project_id) WHERE status = 'open'",
    "CREATE UNIQUE INDEX threads_customer_question_no ON threads "
    "(project_id, customer_question_no) WHERE is_customer",
    "CREATE INDEX threads_node_id_idx ON threads (node_id)",
    f"""
    CREATE TABLE messages (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        node_id uuid,
        thread_id uuid,
        author_id uuid,
        body varchar(10000) NOT NULL,
        kind message_kind NOT NULL DEFAULT 'message',
        event jsonb,
        needs_answer boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        edited_at timestamptz,
        edited_by uuid,
        revoked_at timestamptz,
        CONSTRAINT messages_pkey PRIMARY KEY (id),
        {project_fk("messages")},
        {node_fk("messages")},
        CONSTRAINT messages_thread_id_fkey FOREIGN KEY (thread_id)
            REFERENCES threads (id) ON DELETE CASCADE,
        {user_fk("messages", "author_id")},
        {user_fk("messages", "edited_by")},
        CONSTRAINT messages_body_min_check CHECK (kind = 'event' OR char_length(body) >= 1),
        CONSTRAINT messages_body_max_check
            CHECK (kind = 'customer_answer' OR char_length(body) <= 4000),
        CONSTRAINT messages_event_check CHECK ((kind = 'event') = (event IS NOT NULL))
    )
    """,
    "CREATE INDEX messages_node_id_created_at_idx ON messages (node_id, created_at)",
    "CREATE INDEX messages_thread_id_created_at_idx ON messages (thread_id, created_at)",
    "CREATE INDEX messages_project_feed_idx ON messages (project_id, created_at) "
    "WHERE node_id IS NULL",
    f"""
    CREATE TABLE message_history (
        id uuid NOT NULL,
        message_id uuid NOT NULL,
        body varchar(10000) NOT NULL,
        edited_by uuid NOT NULL,
        edited_at timestamptz NOT NULL DEFAULT now(),
        reason message_history_reason NOT NULL,
        CONSTRAINT message_history_pkey PRIMARY KEY (id),
        CONSTRAINT message_history_message_id_fkey FOREIGN KEY (message_id)
            REFERENCES messages (id) ON DELETE CASCADE,
        {user_fk("message_history", "edited_by")}
    )
    """,
    "CREATE INDEX message_history_message_id_edited_at_idx "
    "ON message_history (message_id, edited_at)",
    """
    CREATE TABLE message_addressees (
        message_id uuid NOT NULL,
        target_type addressee_type NOT NULL,
        target_id uuid,
        CONSTRAINT message_addressees_message_id_fkey FOREIGN KEY (message_id)
            REFERENCES messages (id) ON DELETE CASCADE,
        CONSTRAINT message_addressees_message_id_target_type_target_id_key
            UNIQUE NULLS NOT DISTINCT (message_id, target_type, target_id),
        CONSTRAINT message_addressees_target_check
            CHECK ((target_type IN ('user', 'discipline')) = (target_id IS NOT NULL))
    )
    """,
    "CREATE INDEX message_addressees_target_type_target_id_idx "
    "ON message_addressees (target_type, target_id)",
    f"""
    CREATE TABLE project_notes (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        node_id uuid,
        author_id uuid NOT NULL,
        body varchar(4000) NOT NULL,
        edited_at timestamptz,{AUDIT},
        CONSTRAINT project_notes_pkey PRIMARY KEY (id),
        {project_fk("project_notes")},
        {node_fk("project_notes")},
        {user_fk("project_notes", "author_id")},
        CONSTRAINT project_notes_body_check CHECK (char_length(body) >= 1),
        {audit_fk("project_notes")}
    )
    """,
    "CREATE INDEX project_notes_project_id_node_id_created_at_idx "
    "ON project_notes (project_id, node_id, created_at)",
    f"""
    CREATE TABLE notifications (
        id uuid NOT NULL,
        user_id uuid NOT NULL,
        project_id uuid,
        node_id uuid,
        kind text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{{}}',
        created_at timestamptz NOT NULL DEFAULT now(),
        read_at timestamptz,
        emailed_at timestamptz,
        CONSTRAINT notifications_pkey PRIMARY KEY (id),
        {user_fk("notifications", "user_id")},
        {project_fk("notifications")},
        {node_fk("notifications", "SET NULL")}
    )
    """,
    "CREATE INDEX notifications_unread_idx ON notifications (user_id) WHERE read_at IS NULL",
    "CREATE INDEX notifications_user_id_created_at_idx ON notifications (user_id, created_at DESC)",
    "CREATE INDEX notifications_created_at_idx ON notifications (created_at)",
    # G-5: только INSERT (и чтение) для роли приложения
    "REVOKE UPDATE, DELETE, TRUNCATE ON message_history FROM estimator_app",
]

DOWNGRADE = [
    "DROP TABLE notifications",
    "DROP TABLE project_notes",
    "DROP TABLE message_addressees",
    "DROP TABLE message_history",
    "DROP TABLE messages",
    "DROP TABLE threads",
    "DROP TYPE addressee_type",
    "DROP TYPE message_history_reason",
    "DROP TYPE message_kind",
    "DROP TYPE customer_question_status",
    "DROP TYPE thread_status",
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
