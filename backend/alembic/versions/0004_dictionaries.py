"""Справочники: фазы, дисциплины, типы узлов, профили, метки, соотношения, календарь, НДС, валюты.

Ревизия: 0004_dictionaries
Предыдущая: 0003_audit
Задача PLAN.md: DB-004. Шаг: expand.

contracts/db/schema.md 2.2. ``app_params`` — ключи ``method.*`` в ``system_settings`` (DB-D01).
Внешний ключ ``node_types.project_id → projects`` добавляет ревизия проектов (DB-005).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_dictionaries"
down_revision: str | None = "0003_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Аудиторские поля G-4
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


UPGRADE = [
    "CREATE TYPE node_type_proposal AS ENUM ('none', 'proposed', 'accepted', 'merged', 'rejected')",
    "CREATE TYPE comment_tag_category AS ENUM ('assumption', 'constraint', 'risk', 'tech')",
    f"""
    CREATE TABLE phases (
        id uuid NOT NULL,
        name varchar(100) NOT NULL,
        sort_order integer NOT NULL,
        is_cross_cutting boolean NOT NULL DEFAULT false,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT phases_pkey PRIMARY KEY (id),
        {audit_fk("phases")}
    )
    """,
    "CREATE UNIQUE INDEX phases_one_cross_cutting ON phases ((true)) WHERE is_cross_cutting",
    "CREATE INDEX phases_sort_order_idx ON phases (sort_order)",
    f"""
    CREATE TABLE disciplines (
        id uuid NOT NULL,
        name varchar(100) NOT NULL,
        short_name varchar(12) NOT NULL,
        color varchar(7) NOT NULL,
        default_profile_id uuid,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT disciplines_pkey PRIMARY KEY (id),
        CONSTRAINT disciplines_name_key UNIQUE (name),
        CONSTRAINT disciplines_color_check CHECK (color ~ '^#[0-9A-Fa-f]{{6}}$'),
        {audit_fk("disciplines")}
    )
    """,
    f"""
    CREATE TABLE node_types (
        id uuid NOT NULL,
        name varchar(50) NOT NULL,
        icon text NOT NULL,
        norms jsonb NOT NULL DEFAULT '[]',
        is_active boolean NOT NULL DEFAULT true,
        is_system boolean NOT NULL DEFAULT false,
        project_id uuid,
        proposal_status node_type_proposal NOT NULL DEFAULT 'none',
        merged_into_id uuid,{AUDIT},
        CONSTRAINT node_types_pkey PRIMARY KEY (id),
        CONSTRAINT node_types_merged_into_id_fkey FOREIGN KEY (merged_into_id)
            REFERENCES node_types (id) ON DELETE RESTRICT,
        CONSTRAINT node_types_norms_array_check CHECK (jsonb_typeof(norms) = 'array'),
        CONSTRAINT node_types_system_active_check CHECK (NOT is_system OR is_active),
        CONSTRAINT node_types_proposal_scope_check
            CHECK ((project_id IS NULL) = (proposal_status IN ('none', 'accepted'))),
        CONSTRAINT node_types_merged_check
            CHECK ((proposal_status = 'merged') = (merged_into_id IS NOT NULL)),
        {audit_fk("node_types")}
    )
    """,
    "CREATE UNIQUE INDEX node_types_one_system ON node_types ((true)) WHERE is_system",
    "CREATE INDEX node_types_project_id_idx ON node_types (project_id) "
    "WHERE project_id IS NOT NULL",
    "CREATE INDEX node_types_proposed_idx ON node_types (proposal_status) "
    "WHERE proposal_status = 'proposed'",
    f"""
    CREATE TABLE discipline_profiles (
        id uuid NOT NULL,
        discipline_id uuid NOT NULL,
        name varchar(100) NOT NULL,
        type_chain uuid[] NOT NULL,{AUDIT},
        CONSTRAINT discipline_profiles_pkey PRIMARY KEY (id),
        CONSTRAINT discipline_profiles_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT discipline_profiles_discipline_id_name_key UNIQUE (discipline_id, name),
        CONSTRAINT discipline_profiles_type_chain_check
            CHECK (cardinality(type_chain) BETWEEN 1 AND 8),
        {audit_fk("discipline_profiles")}
    )
    """,
    "ALTER TABLE disciplines ADD CONSTRAINT disciplines_default_profile_id_fkey "
    "FOREIGN KEY (default_profile_id) REFERENCES discipline_profiles (id) "
    "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
    f"""
    CREATE TABLE comment_tags (
        id uuid NOT NULL,
        name varchar(50) NOT NULL,
        short_name varchar(12) NOT NULL,
        color varchar(7) NOT NULL,
        category comment_tag_category NOT NULL,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT comment_tags_pkey PRIMARY KEY (id),
        CONSTRAINT comment_tags_color_check CHECK (color ~ '^#[0-9A-Fa-f]{{6}}$'),
        {audit_fk("comment_tags")}
    )
    """,
    f"""
    CREATE TABLE control_ratios (
        id uuid NOT NULL,
        discipline_a_id uuid NOT NULL,
        disciplines_b uuid[] NOT NULL,
        min_pct numeric(5, 2) NOT NULL,
        max_pct numeric(5, 2) NOT NULL,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT control_ratios_pkey PRIMARY KEY (id),
        CONSTRAINT control_ratios_discipline_a_id_fkey FOREIGN KEY (discipline_a_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT control_ratios_disciplines_b_check CHECK (cardinality(disciplines_b) >= 1),
        CONSTRAINT control_ratios_range_check
            CHECK (0 <= min_pct AND min_pct <= max_pct AND max_pct <= 999.99),
        {audit_fk("control_ratios")}
    )
    """,
    f"""
    CREATE TABLE work_calendar (
        date date NOT NULL,
        is_working boolean NOT NULL,
        year smallint NOT NULL,{AUDIT},
        CONSTRAINT work_calendar_pkey PRIMARY KEY (date),
        CONSTRAINT work_calendar_year_check CHECK (year = EXTRACT(YEAR FROM date)),
        {audit_fk("work_calendar")}
    )
    """,
    "CREATE INDEX work_calendar_year_idx ON work_calendar (year)",
    f"""
    CREATE TABLE loss_reasons (
        id uuid NOT NULL,
        name varchar(100) NOT NULL,
        is_other boolean NOT NULL DEFAULT false,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT loss_reasons_pkey PRIMARY KEY (id),
        {audit_fk("loss_reasons")}
    )
    """,
    f"""
    CREATE TABLE vat_rates (
        id uuid NOT NULL,
        name varchar(50) NOT NULL,
        percent numeric(5, 2),
        is_active boolean NOT NULL DEFAULT true,
        is_default boolean NOT NULL DEFAULT false,{AUDIT},
        CONSTRAINT vat_rates_pkey PRIMARY KEY (id),
        CONSTRAINT vat_rates_percent_check CHECK (percent IS NULL OR percent BETWEEN 0 AND 100),
        CONSTRAINT vat_rates_default_active_check CHECK (NOT is_default OR is_active),
        {audit_fk("vat_rates")}
    )
    """,
    "CREATE UNIQUE INDEX vat_rates_one_default ON vat_rates ((true)) WHERE is_default",
    f"""
    CREATE TABLE currencies (
        code char(3) NOT NULL,
        symbol varchar(8) NOT NULL,
        is_active boolean NOT NULL DEFAULT true,{AUDIT},
        CONSTRAINT currencies_pkey PRIMARY KEY (code),
        CONSTRAINT currencies_code_check CHECK (code ~ '^[A-Z]{{3}}$'),
        CONSTRAINT currencies_rub_active_check CHECK (code <> 'RUB' OR is_active),
        {audit_fk("currencies")}
    )
    """,
]

DOWNGRADE = [
    "DROP TABLE currencies",
    "DROP TABLE vat_rates",
    "DROP TABLE loss_reasons",
    "DROP TABLE work_calendar",
    "DROP TABLE control_ratios",
    "DROP TABLE comment_tags",
    "ALTER TABLE disciplines DROP CONSTRAINT disciplines_default_profile_id_fkey",
    "DROP TABLE discipline_profiles",
    "DROP TABLE node_types",
    "DROP TABLE disciplines",
    "DROP TABLE phases",
    "DROP TYPE comment_tag_category",
    "DROP TYPE node_type_proposal",
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
