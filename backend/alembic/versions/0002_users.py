"""Пользователи, роли, сессии, токены, настройки.

Ревизия: 0002_users
Предыдущая: 0001_base
Задача PLAN.md: DB-003. Шаг: expand.

Таблицы contracts/db/schema.md 2.1 и ``auth_tokens`` (раздел 3): ``users``, ``user_roles``,
``password_history``, ``backup_codes``, ``known_devices``, ``sessions``, ``system_settings``,
``auth_tokens``. ``totp_used_codes`` живёт в Redis (DB-D02).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_users"
down_revision: str | None = "0001_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = [
    "CREATE TYPE user_source AS ENUM ('local', 'ad')",
    "CREATE TYPE user_status AS ENUM ('active', 'blocked', 'pending_password', 'anonymized')",
    "CREATE TYPE user_block_reason AS ENUM "
    "('manual', 'ad_disabled', 'ad_group', 'ad_missing', 'not_matched')",
    "CREATE TYPE system_role AS ENUM "
    "('superadmin', 'admin', 'moderator', 'presale', 'presale_head', 'security_auditor')",
    "CREATE TYPE role_source AS ENUM ('manual', 'ad_group')",
    "CREATE TYPE auth_token_kind AS ENUM ('activation', 'password_reset')",
    "CREATE SEQUENCE users_anonymized_no_seq AS integer START 1",
    """
    CREATE TABLE users (
        id uuid NOT NULL,
        login citext NOT NULL,
        email citext,
        full_name varchar(200) NOT NULL,
        timezone text,
        source user_source NOT NULL DEFAULT 'local',
        ad_object_guid uuid,
        password_hash text,
        password_changed_at timestamptz,
        totp_secret_enc bytea,
        totp_enabled boolean NOT NULL DEFAULT false,
        status user_status NOT NULL DEFAULT 'pending_password',
        block_reason user_block_reason,
        blocked_at timestamptz,
        last_login_at timestamptz,
        notify_digest boolean NOT NULL DEFAULT true,
        notify_questions boolean NOT NULL DEFAULT true,
        last_digest_at timestamptz,
        anonymized_no integer,
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by uuid,
        CONSTRAINT users_pkey PRIMARY KEY (id),
        CONSTRAINT users_login_key UNIQUE (login),
        CONSTRAINT users_ad_object_guid_key UNIQUE (ad_object_guid),
        CONSTRAINT users_anonymized_no_key UNIQUE (anonymized_no),
        CONSTRAINT users_created_by_fkey FOREIGN KEY (created_by)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT users_updated_by_fkey FOREIGN KEY (updated_by)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT users_login_length_check CHECK (char_length(login) BETWEEN 3 AND 64),
        CONSTRAINT users_email_length_check CHECK (char_length(email) <= 254),
        CONSTRAINT users_ad_guid_source_check CHECK (source = 'ad' OR ad_object_guid IS NULL),
        CONSTRAINT users_password_source_check CHECK (source = 'local' OR password_hash IS NULL),
        CONSTRAINT users_totp_secret_check CHECK (NOT totp_enabled OR totp_secret_enc IS NOT NULL),
        CONSTRAINT users_block_reason_check
            CHECK ((status = 'blocked') = (block_reason IS NOT NULL)),
        CONSTRAINT users_anonymized_no_check
            CHECK ((status = 'anonymized') = (anonymized_no IS NOT NULL))
    )
    """,
    "ALTER SEQUENCE users_anonymized_no_seq OWNED BY users.anonymized_no",
    "CREATE UNIQUE INDEX users_email_uq ON users (email) WHERE email IS NOT NULL",
    """
    CREATE TABLE user_roles (
        user_id uuid NOT NULL,
        role system_role NOT NULL,
        source role_source NOT NULL DEFAULT 'manual',
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid,
        CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role),
        CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT user_roles_created_by_fkey FOREIGN KEY (created_by)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT user_roles_ad_group_check
            CHECK (source = 'manual' OR role IN ('moderator', 'presale'))
    )
    """,
    "CREATE INDEX user_roles_role_idx ON user_roles (role)",
    """
    CREATE TABLE password_history (
        id uuid NOT NULL,
        user_id uuid NOT NULL,
        password_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT password_history_pkey PRIMARY KEY (id),
        CONSTRAINT password_history_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX password_history_user_id_created_at_idx "
    "ON password_history (user_id, created_at DESC)",
    """
    CREATE TABLE backup_codes (
        id uuid NOT NULL,
        user_id uuid NOT NULL,
        code_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        used_at timestamptz,
        CONSTRAINT backup_codes_pkey PRIMARY KEY (id),
        CONSTRAINT backup_codes_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX backup_codes_unused_idx ON backup_codes (user_id) WHERE used_at IS NULL",
    """
    CREATE TABLE known_devices (
        user_id uuid NOT NULL,
        ua_family text NOT NULL,
        subnet cidr NOT NULL,
        first_seen_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL,
        CONSTRAINT known_devices_pkey PRIMARY KEY (user_id, ua_family, subnet),
        CONSTRAINT known_devices_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE sessions (
        id_hash bytea NOT NULL,
        user_id uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        ip inet NOT NULL,
        user_agent varchar(512),
        mfa_passed boolean NOT NULL DEFAULT false,
        step_up_until timestamptz,
        revoked_at timestamptz,
        revoke_reason text,
        CONSTRAINT sessions_pkey PRIMARY KEY (id_hash),
        CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX sessions_active_idx ON sessions (user_id) WHERE revoked_at IS NULL",
    "CREATE INDEX sessions_expires_at_idx ON sessions (expires_at)",
    r"""
    CREATE TABLE system_settings (
        key text NOT NULL,
        value jsonb NOT NULL,
        updated_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT system_settings_pkey PRIMARY KEY (key),
        CONSTRAINT system_settings_updated_by_fkey FOREIGN KEY (updated_by)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT system_settings_key_format_check
            CHECK (key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')
    )
    """,
    """
    CREATE TABLE auth_tokens (
        id uuid NOT NULL,
        user_id uuid NOT NULL,
        kind auth_token_kind NOT NULL,
        token_hash bytea NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        revoked_at timestamptz,
        CONSTRAINT auth_tokens_pkey PRIMARY KEY (id),
        CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash),
        CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE RESTRICT,
        CONSTRAINT auth_tokens_created_by_fkey FOREIGN KEY (created_by)
            REFERENCES users (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX auth_tokens_active_idx ON auth_tokens (user_id) "
    "WHERE used_at IS NULL AND revoked_at IS NULL",
]

DOWNGRADE = [
    "DROP TABLE auth_tokens",
    "DROP TABLE system_settings",
    "DROP TABLE sessions",
    "DROP TABLE known_devices",
    "DROP TABLE backup_codes",
    "DROP TABLE password_history",
    "DROP TABLE user_roles",
    "DROP TABLE users",
    "DROP TYPE auth_token_kind",
    "DROP TYPE role_source",
    "DROP TYPE system_role",
    "DROP TYPE user_block_reason",
    "DROP TYPE user_status",
    "DROP TYPE user_source",
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
