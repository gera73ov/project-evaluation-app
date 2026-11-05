"""Снимки оценки, файлы выгрузок, документы заказчика.

Ревизия: 0009_snapshots_files
Предыдущая: 0008_discussions
Задача PLAN.md: DB-008. Шаг: expand.

contracts/db/schema.md 2.6 (``snapshots``, ``export_files``) и 2.5 (``customer_documents``).
Снимок неизменяем (FR-SNAP-02): роль приложения может только добавить снимок и пометить его
«ошибочным» — ``UPDATE`` лишь столбцов ``is_invalid``, ``invalidated_by``, ``invalidated_at``,
без ``DELETE``. Удаление вместе с проектом (``estimator project purge``) идёт каскадом от
``projects`` от имени владельца таблицы. Ключ файла документа хранится зашифрованным мастер-ключом
(SEC-CRYPT-06).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_snapshots_files"
down_revision: str | None = "0008_discussions"
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


UPGRADE = [
    "CREATE TYPE scan_status AS ENUM ('pending', 'clean', 'infected', 'error')",
    "CREATE TYPE export_status AS ENUM ('pending', 'ready', 'failed')",
    f"""
    CREATE TABLE snapshots (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        name varchar(100) NOT NULL,
        description varchar(1000) NOT NULL DEFAULT '',
        project_version bigint NOT NULL,
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        is_invalid boolean NOT NULL DEFAULT false,
        invalidated_by uuid,
        invalidated_at timestamptz,
        payload jsonb NOT NULL,
        money_payload jsonb,
        payload_sha256 bytea NOT NULL,
        CONSTRAINT snapshots_pkey PRIMARY KEY (id),
        {project_fk("snapshots")},
        {user_fk("snapshots", "created_by")},
        {user_fk("snapshots", "invalidated_by")},
        CONSTRAINT snapshots_name_check CHECK (char_length(name) >= 1)
    )
    """,
    "CREATE INDEX snapshots_project_id_created_at_idx ON snapshots (project_id, created_at)",
    f"""
    CREATE TABLE export_files (
        id uuid NOT NULL,
        user_id uuid NOT NULL,
        project_id uuid,
        kind text NOT NULL,
        snapshot_id uuid,
        status export_status NOT NULL DEFAULT 'pending',
        file_name varchar(255),
        path text,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        CONSTRAINT export_files_pkey PRIMARY KEY (id),
        {user_fk("export_files", "user_id")},
        {project_fk("export_files")},
        CONSTRAINT export_files_snapshot_id_fkey FOREIGN KEY (snapshot_id)
            REFERENCES snapshots (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX export_files_user_id_created_at_idx ON export_files (user_id, created_at DESC)",
    "CREATE INDEX export_files_expires_at_idx ON export_files (expires_at)",
    f"""
    CREATE TABLE customer_documents (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        file_name varchar(255) NOT NULL,
        mime text NOT NULL,
        size_bytes bigint NOT NULL,
        storage_key uuid NOT NULL,
        key_enc bytea NOT NULL,
        scan_status scan_status NOT NULL DEFAULT 'pending',
        uploaded_by uuid NOT NULL,
        uploaded_at timestamptz NOT NULL DEFAULT now(),
        deleted_at timestamptz,
        deleted_by uuid,{AUDIT},
        CONSTRAINT customer_documents_pkey PRIMARY KEY (id),
        {project_fk("customer_documents")},
        {user_fk("customer_documents", "uploaded_by")},
        {user_fk("customer_documents", "deleted_by")},
        CONSTRAINT customer_documents_storage_key_key UNIQUE (storage_key),
        CONSTRAINT customer_documents_mime_check CHECK (mime IN ('application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')),
        CONSTRAINT customer_documents_size_bytes_check
            CHECK (size_bytes BETWEEN 1 AND 52428800),
        {audit_fk("customer_documents")}
    )
    """,
    "CREATE INDEX customer_documents_live_idx ON customer_documents (project_id) "
    "WHERE deleted_at IS NULL",
    # FR-SNAP-02: снимок не меняется, кроме отметки «ошибочный»
    "REVOKE UPDATE, DELETE, TRUNCATE ON snapshots FROM estimator_app",
    "GRANT UPDATE (is_invalid, invalidated_by, invalidated_at) ON snapshots TO estimator_app",
]

DOWNGRADE = [
    "DROP TABLE customer_documents",
    "DROP TABLE export_files",
    "DROP TABLE snapshots",
    "DROP TYPE export_status",
    "DROP TYPE scan_status",
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
