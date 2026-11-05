"""Проекты, деньги, итоги, команда, фазы и дисциплины проекта, статусы веток, режим поддержки.

Ревизия: 0006_projects
Предыдущая: 0005_seed_dictionaries
Задача PLAN.md: DB-005. Шаг: expand.

contracts/db/schema.md 2.3 (и ``project_totals_daily`` по GAP-01). Деньги — только в
``project_money``, ``project_rates`` и денежных столбцах ``project_totals``/``project_totals_daily``
(G-11); их ORM-модели — модуль ``estimator.db.models.money``. Внутри проекта ключи
``ON DELETE CASCADE`` (``estimator project purge``, BR-PRJ-04), на ``users`` — ``RESTRICT`` (G-12).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_projects"
down_revision: str | None = "0005_seed_dictionaries"
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


TOTALS = """
        e numeric(14, 2),
        p80 numeric(14, 2),
        p90 numeric(14, 2),
        cost_rub numeric(20, 0),
        quote_rub numeric(20, 0),
        quote_cur numeric(20, 0)"""

UPGRADE = [
    "CREATE TYPE project_status AS ENUM "
    "('preparation', 'estimation', 'consolidation', 'completed', 'archived')",
    "CREATE TYPE project_outcome AS ENUM ('unknown', 'won', 'lost', 'cancelled')",
    "CREATE TYPE quote_figure AS ENUM ('e', 'p80', 'p90')",
    "CREATE TYPE detail_level AS ENUM ('coarse', 'medium', 'detailed')",
    "CREATE TYPE project_role AS ENUM ('moderator', 'expert', 'presale')",
    "CREATE TYPE branch_status_value AS ENUM ('not_started', 'draft', 'done', 'not_needed')",
    f"""
    CREATE TABLE projects (
        id uuid NOT NULL,
        name varchar(200) NOT NULL,
        customer varchar(200) NOT NULL,
        description varchar(10000) NOT NULL DEFAULT '',
        next_question_no integer NOT NULL DEFAULT 1,
        status project_status NOT NULL DEFAULT 'preparation',
        outcome project_outcome NOT NULL DEFAULT 'unknown',
        loss_reason_id uuid,
        loss_reason_text varchar(500),
        quote_figure quote_figure NOT NULL DEFAULT 'p80',
        duration_weeks smallint,
        no_moderator_since timestamptz,
        detail_level detail_level NOT NULL DEFAULT 'medium',
        pm_percent numeric(5, 2) NOT NULL,
        pm_percent_reason varchar(1000) NOT NULL DEFAULT '',
        deadline date,
        version bigint NOT NULL DEFAULT 0,
        completed_at timestamptz,
        archived_at timestamptz,
        cancel_reason varchar(500),
        copied_from_id uuid,{AUDIT},
        CONSTRAINT projects_pkey PRIMARY KEY (id),
        CONSTRAINT projects_loss_reason_id_fkey FOREIGN KEY (loss_reason_id)
            REFERENCES loss_reasons (id) ON DELETE RESTRICT,
        CONSTRAINT projects_copied_from_id_fkey FOREIGN KEY (copied_from_id)
            REFERENCES projects (id) ON DELETE SET NULL,
        CONSTRAINT projects_name_length_check CHECK (char_length(name) >= 3),
        CONSTRAINT projects_customer_length_check CHECK (char_length(customer) >= 1),
        CONSTRAINT projects_next_question_no_check CHECK (next_question_no >= 1),
        CONSTRAINT projects_loss_reason_check CHECK (outcome = 'lost' OR loss_reason_id IS NULL),
        CONSTRAINT projects_duration_weeks_check CHECK (duration_weeks BETWEEN 1 AND 260),
        CONSTRAINT projects_pm_percent_check
            CHECK (pm_percent BETWEEN 0 AND 50 AND pm_percent * 2 = trunc(pm_percent * 2)),
        CONSTRAINT projects_cancel_reason_check
            CHECK (cancel_reason IS NULL OR char_length(cancel_reason) >= 10),
        {audit_fk("projects")}
    )
    """,
    "CREATE INDEX projects_status_idx ON projects (status)",
    "CREATE INDEX projects_no_moderator_idx ON projects (no_moderator_since) "
    "WHERE no_moderator_since IS NOT NULL",
    "CREATE INDEX projects_completed_idx ON projects (completed_at) WHERE status = 'completed'",
    "CREATE INDEX projects_created_at_idx ON projects (created_at)",
    "ALTER TABLE node_types ADD CONSTRAINT node_types_project_id_fkey FOREIGN KEY (project_id) "
    "REFERENCES projects (id) ON DELETE CASCADE",
    f"""
    CREATE TABLE project_money (
        project_id uuid NOT NULL,
        currency char(3) NOT NULL DEFAULT 'RUB',
        exchange_rate numeric(12, 4) NOT NULL DEFAULT 1,
        vat_rate_id uuid NOT NULL,
        vat_percent numeric(5, 2),
        contract_amount numeric(20, 0),
        updated_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT project_money_pkey PRIMARY KEY (project_id),
        {project_fk("project_money")},
        CONSTRAINT project_money_currency_fkey FOREIGN KEY (currency)
            REFERENCES currencies (code) ON DELETE RESTRICT,
        CONSTRAINT project_money_vat_rate_id_fkey FOREIGN KEY (vat_rate_id)
            REFERENCES vat_rates (id) ON DELETE RESTRICT,
        CONSTRAINT project_money_updated_by_fkey FOREIGN KEY (updated_by)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT project_money_exchange_rate_check CHECK (exchange_rate > 0),
        CONSTRAINT project_money_rub_rate_check CHECK (currency <> 'RUB' OR exchange_rate = 1),
        CONSTRAINT project_money_contract_amount_check CHECK (contract_amount >= 0)
    )
    """,
    f"""
    CREATE TABLE project_totals (
        project_id uuid NOT NULL,{TOTALS},
        rates_missing boolean NOT NULL DEFAULT false,
        project_version bigint NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT project_totals_pkey PRIMARY KEY (project_id),
        {project_fk("project_totals")}
    )
    """,
    f"""
    CREATE TABLE project_totals_daily (
        project_id uuid NOT NULL,
        date date NOT NULL,{TOTALS},
        updated_at timestamptz NOT NULL,
        CONSTRAINT project_totals_daily_pkey PRIMARY KEY (project_id, date),
        {project_fk("project_totals_daily")}
    )
    """,
    f"""
    CREATE TABLE project_rates (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        discipline_id uuid,
        rate_rub numeric(12, 0) NOT NULL,{AUDIT},
        CONSTRAINT project_rates_pkey PRIMARY KEY (id),
        {project_fk("project_rates")},
        CONSTRAINT project_rates_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT project_rates_project_id_discipline_id_key
            UNIQUE NULLS NOT DISTINCT (project_id, discipline_id),
        CONSTRAINT project_rates_rate_rub_check CHECK (rate_rub BETWEEN 0 AND 1000000),
        {audit_fk("project_rates")}
    )
    """,
    f"""
    CREATE TABLE project_members (
        id uuid NOT NULL,
        project_id uuid NOT NULL,
        user_id uuid NOT NULL,
        role project_role NOT NULL,
        discipline_id uuid,
        is_reviewer boolean NOT NULL DEFAULT false,
        added_by_admin_self boolean NOT NULL DEFAULT false,
        notified_at timestamptz,{AUDIT},
        CONSTRAINT project_members_pkey PRIMARY KEY (id),
        {project_fk("project_members")},
        CONSTRAINT project_members_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT project_members_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT project_members_project_id_user_id_role_discipline_id_key
            UNIQUE NULLS NOT DISTINCT (project_id, user_id, role, discipline_id),
        CONSTRAINT project_members_discipline_check
            CHECK ((role = 'expert') = (discipline_id IS NOT NULL)),
        CONSTRAINT project_members_reviewer_check CHECK (NOT is_reviewer OR role = 'expert'),
        {audit_fk("project_members")}
    )
    """,
    "CREATE INDEX project_members_user_id_idx ON project_members (user_id)",
    "CREATE INDEX project_members_project_id_role_idx ON project_members (project_id, role)",
    f"""
    CREATE TABLE project_phases (
        project_id uuid NOT NULL,
        phase_id uuid NOT NULL,
        is_enabled boolean NOT NULL DEFAULT true,
        in_pm_base boolean NOT NULL DEFAULT true,
        CONSTRAINT project_phases_pkey PRIMARY KEY (project_id, phase_id),
        {project_fk("project_phases")},
        CONSTRAINT project_phases_phase_id_fkey FOREIGN KEY (phase_id)
            REFERENCES phases (id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE project_disciplines (
        project_id uuid NOT NULL,
        discipline_id uuid NOT NULL,
        profile_id uuid NOT NULL,{AUDIT},
        CONSTRAINT project_disciplines_pkey PRIMARY KEY (project_id, discipline_id),
        {project_fk("project_disciplines")},
        CONSTRAINT project_disciplines_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT project_disciplines_profile_id_fkey FOREIGN KEY (profile_id)
            REFERENCES discipline_profiles (id) ON DELETE RESTRICT,
        {audit_fk("project_disciplines")}
    )
    """,
    f"""
    CREATE TABLE branch_status (
        project_id uuid NOT NULL,
        phase_id uuid NOT NULL,
        discipline_id uuid NOT NULL,
        status branch_status_value NOT NULL DEFAULT 'not_started',
        changed_by uuid,
        changed_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT branch_status_pkey PRIMARY KEY (project_id, phase_id, discipline_id),
        {project_fk("branch_status")},
        CONSTRAINT branch_status_phase_id_fkey FOREIGN KEY (phase_id)
            REFERENCES phases (id) ON DELETE RESTRICT,
        CONSTRAINT branch_status_discipline_id_fkey FOREIGN KEY (discipline_id)
            REFERENCES disciplines (id) ON DELETE RESTRICT,
        CONSTRAINT branch_status_changed_by_fkey FOREIGN KEY (changed_by)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE support_sessions (
        id uuid NOT NULL,
        admin_id uuid NOT NULL,
        project_id uuid NOT NULL,
        reason varchar(500) NOT NULL,
        started_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        ended_at timestamptz,
        CONSTRAINT support_sessions_pkey PRIMARY KEY (id),
        {project_fk("support_sessions")},
        CONSTRAINT support_sessions_admin_id_fkey FOREIGN KEY (admin_id)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT support_sessions_reason_check CHECK (char_length(reason) >= 10),
        CONSTRAINT support_sessions_expires_check
            CHECK (expires_at <= started_at + interval '60 minutes')
    )
    """,
    "CREATE INDEX support_sessions_admin_project_idx "
    "ON support_sessions (admin_id, project_id, expires_at)",
]

DOWNGRADE = [
    "DROP TABLE support_sessions",
    "DROP TABLE branch_status",
    "DROP TABLE project_disciplines",
    "DROP TABLE project_phases",
    "DROP TABLE project_members",
    "DROP TABLE project_rates",
    "DROP TABLE project_totals_daily",
    "DROP TABLE project_totals",
    "DROP TABLE project_money",
    "ALTER TABLE node_types DROP CONSTRAINT node_types_project_id_fkey",
    "DROP TABLE projects",
    "DROP TYPE branch_status_value",
    "DROP TYPE project_role",
    "DROP TYPE detail_level",
    "DROP TYPE quote_figure",
    "DROP TYPE project_outcome",
    "DROP TYPE project_status",
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
