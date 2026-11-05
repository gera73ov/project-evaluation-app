"""Журнал аудита: audit.audit_log с партициями, якорь purge, функция записи под блокировкой.

Ревизия: 0003_audit
Предыдущая: 0002_users
Задача PLAN.md: DB-009. Шаг: expand.

SPEC SEC-AUD-02…04; contracts/db/schema.md 2.6 и раздел 3 (``audit.audit_anchor``);
contracts/audit-events.yaml раздел 1 (поля записи).

Хэш-цепочка (SEC-AUD-03) считается в БД, одной функцией для записи и проверки:

* ``audit.canonical_json(jsonb)`` — канонический JSON по RFC 8785 для данных журнала: ключи
  объектов по возрастанию кодовых точек, без пробелов, строки с экранированием JSON, числа без
  лишних нулей дробной части. Ограничение: ключи вне BMP сортируются по кодовым точкам, а не по
  UTF-16 (в журнале ключи — латиница, contracts/audit-events.yaml).
* ``audit.record_json(audit.audit_log)`` — объект записи с именами полей контракта
  (``time``, ``type``, ``result``, ``user_id``, ``login``, ``ip``, ``user_agent``, ``session_hash``,
  ``object_type``, ``object_id``, ``details``, ``prev_hash``): время ISO 8601 UTC с микросекундами
  (``2026-11-05T15:14:37.123456Z``), ``ip`` без маски, байтовые поля — hex, отсутствующие —
  ``null``.
* ``audit.row_hash(audit.audit_log)`` = ``SHA-256(prev_hash ‖ UTF-8(canonical_json(record_json)))``,
  где ``prev_hash`` — 32 байта (не hex).
* ``audit.append(…)`` — единственный способ вставки для ``estimator_app``: под
  ``pg_advisory_xact_lock`` берёт ``hash`` последней записи (или якоря purge, или 32 нулевых
  байта), ставит время ``clock_timestamp()``, считает хэш и вставляет запись.
* ``audit.ensure_partitions(n)`` — партиции на текущий месяц и ``n`` месяцев вперёд
  (периодическая задача ``estimator.db.ensure_audit_partitions``). Партиция ``audit_log_default``
  страхует запись, если задача не отработала.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_audit"
down_revision: str | None = "0002_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Ключи pg_advisory_xact_lock записаны в SQL числом (ASCII «audit» и «audip»):
# AUDIT_LOCK_KEY = 0x6175646974 = 418581342580 — цепочка аудита, его же берёт `audit purge`;
# PARTITION_LOCK_KEY = 0x6175646970 = 418581342576 — создание партиций.

UPGRADE = [
    "CREATE TYPE audit.audit_result AS ENUM ('success', 'failure', 'denied')",
    """
    CREATE TABLE audit.audit_log (
        id bigint GENERATED ALWAYS AS IDENTITY,
        ts timestamptz NOT NULL,
        event_type text NOT NULL,
        result audit.audit_result NOT NULL,
        user_id uuid,
        login text,
        ip inet,
        user_agent varchar(512),
        session_hash bytea,
        object_type text,
        object_id text,
        details jsonb NOT NULL DEFAULT '{}',
        prev_hash bytea NOT NULL,
        hash bytea NOT NULL,
        CONSTRAINT audit_log_pkey PRIMARY KEY (ts, id),
        CONSTRAINT audit_log_details_object_check CHECK (jsonb_typeof(details) = 'object')
    ) PARTITION BY RANGE (ts)
    """,
    "CREATE INDEX audit_log_id_idx ON audit.audit_log (id)",
    "CREATE INDEX audit_log_ts_idx ON audit.audit_log (ts)",
    "CREATE INDEX audit_log_user_id_ts_idx ON audit.audit_log (user_id, ts)",
    "CREATE INDEX audit_log_event_type_ts_idx ON audit.audit_log (event_type, ts)",
    "CREATE TABLE audit.audit_log_default PARTITION OF audit.audit_log DEFAULT",
    """
    CREATE TABLE audit.audit_anchor (
        id smallint NOT NULL,
        last_purged_id bigint NOT NULL,
        last_purged_hash bytea NOT NULL,
        purged_until timestamptz NOT NULL,
        purged_at timestamptz NOT NULL,
        CONSTRAINT audit_anchor_pkey PRIMARY KEY (id),
        CONSTRAINT audit_anchor_single_row_check CHECK (id = 1)
    )
    """,
    r"""
    CREATE FUNCTION audit.canonical_json(j jsonb) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        out text;
    BEGIN
        CASE jsonb_typeof(j)
        WHEN 'object' THEN
            SELECT '{' || coalesce(string_agg(
                       to_json(e.key)::text || ':' || audit.canonical_json(e.value),
                       ',' ORDER BY e.key COLLATE "C"), '') || '}'
              INTO out FROM jsonb_each(j) AS e;
        WHEN 'array' THEN
            SELECT '[' || coalesce(string_agg(audit.canonical_json(a.value), ',' ORDER BY a.n),
                                   '') || ']'
              INTO out FROM jsonb_array_elements(j) WITH ORDINALITY AS a(value, n);
        WHEN 'number' THEN
            out := trim_scale((j #>> '{}')::numeric)::text;
        ELSE
            -- string (экранирование JSON), true, false, null
            out := j::text;
        END CASE;
        RETURN out;
    END
    $$
    """,
    """
    CREATE FUNCTION audit.record_json(r audit.audit_log) RETURNS jsonb
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path = pg_catalog, pg_temp
    AS $$
        SELECT jsonb_build_object(
            'time', to_char(r.ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'type', r.event_type,
            'result', r.result::text,
            'user_id', r.user_id::text,
            'login', r.login,
            'ip', host(r.ip),
            'user_agent', r.user_agent,
            'session_hash', encode(r.session_hash, 'hex'),
            'object_type', r.object_type,
            'object_id', r.object_id,
            'details', r.details,
            'prev_hash', encode(r.prev_hash, 'hex')
        )
    $$
    """,
    """
    CREATE FUNCTION audit.row_hash(r audit.audit_log) RETURNS bytea
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path = pg_catalog, pg_temp
    AS $$
        SELECT sha256(r.prev_hash || convert_to(audit.canonical_json(audit.record_json(r)), 'UTF8'))
    $$
    """,
    """
    CREATE FUNCTION audit.append(
        p_event_type text,
        p_result audit.audit_result,
        p_user_id uuid DEFAULT NULL,
        p_login text DEFAULT NULL,
        p_ip inet DEFAULT NULL,
        p_user_agent text DEFAULT NULL,
        p_session_hash bytea DEFAULT NULL,
        p_object_type text DEFAULT NULL,
        p_object_id text DEFAULT NULL,
        p_details jsonb DEFAULT '{}'
    ) RETURNS audit.audit_log
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        r audit.audit_log;
    BEGIN
        -- Под REPEATABLE READ снимок взят до блокировки: последняя запись другой транзакции
        -- не видна, и цепочка разветвится.
        IF current_setting('transaction_isolation') <> 'read committed' THEN
            RAISE EXCEPTION 'audit.append требует уровень изоляции READ COMMITTED'
                USING ERRCODE = 'invalid_transaction_state';
        END IF;
        PERFORM pg_advisory_xact_lock(418581342580);  -- AUDIT_LOCK_KEY

        SELECT l.hash INTO r.prev_hash FROM audit.audit_log AS l ORDER BY l.id DESC LIMIT 1;
        IF r.prev_hash IS NULL THEN
            SELECT a.last_purged_hash INTO r.prev_hash FROM audit.audit_anchor AS a WHERE a.id = 1;
        END IF;
        r.prev_hash := coalesce(r.prev_hash, decode(repeat('00', 32), 'hex'));

        r.ts := clock_timestamp();
        r.event_type := p_event_type;
        r.result := p_result;
        r.user_id := p_user_id;
        r.login := p_login;
        r.ip := p_ip;
        r.user_agent := left(p_user_agent, 512);
        r.session_hash := p_session_hash;
        r.object_type := p_object_type;
        r.object_id := p_object_id;
        r.details := coalesce(p_details, '{}'::jsonb);
        r.hash := audit.row_hash(r);

        INSERT INTO audit.audit_log (ts, event_type, result, user_id, login, ip, user_agent,
                                     session_hash, object_type, object_id, details,
                                     prev_hash, hash)
        VALUES (r.ts, r.event_type, r.result, r.user_id, r.login, r.ip, r.user_agent,
                r.session_hash, r.object_type, r.object_id, r.details, r.prev_hash, r.hash)
        RETURNING id INTO r.id;
        RETURN r;
    END
    $$
    """,
    """
    CREATE FUNCTION audit.ensure_partitions(p_months_ahead integer DEFAULT 3) RETURNS integer
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        first_month date := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
        month_start date;
        part_name text;
        created integer := 0;
    BEGIN
        IF p_months_ahead IS NULL OR p_months_ahead < 0 OR p_months_ahead > 24 THEN
            RAISE EXCEPTION 'p_months_ahead вне диапазона 0..24'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        PERFORM pg_advisory_xact_lock(418581342576);  -- PARTITION_LOCK_KEY
        FOR i IN 0..p_months_ahead LOOP
            month_start := (first_month + make_interval(months => i))::date;
            part_name := 'audit_log_' || to_char(month_start, 'YYYYMM');
            IF to_regclass(format('audit.%I', part_name)) IS NULL THEN
                EXECUTE format(
                    'CREATE TABLE audit.%I PARTITION OF audit.audit_log '
                    'FOR VALUES FROM (%L) TO (%L)',
                    part_name,
                    month_start::text || ' 00:00:00+00',
                    (month_start + interval '1 month')::date::text || ' 00:00:00+00');
                created := created + 1;
            END IF;
        END LOOP;
        RETURN created;
    END
    $$
    """,
    "SELECT audit.ensure_partitions(3)",
    # Права (SEC-AUD-03/04): приложение — только чтение и запись через функцию
    "REVOKE ALL ON audit.audit_log, audit.audit_anchor FROM PUBLIC",
    "GRANT SELECT ON audit.audit_log, audit.audit_anchor TO estimator_app",
    "GRANT EXECUTE ON FUNCTION audit.append(text, audit.audit_result, uuid, text, inet, text, "
    "bytea, text, text, jsonb) TO estimator_app",
    "GRANT EXECUTE ON FUNCTION audit.ensure_partitions(integer) TO estimator_app",
    "GRANT EXECUTE ON FUNCTION audit.canonical_json(jsonb), audit.record_json(audit.audit_log), "
    "audit.row_hash(audit.audit_log) TO estimator_app, estimator_audit_purge",
    "GRANT USAGE ON TYPE audit.audit_result TO estimator_app, estimator_audit_purge",
    # Роль purge: удалить старые записи и записать якорь
    "GRANT SELECT, DELETE ON audit.audit_log TO estimator_audit_purge",
    "GRANT SELECT, INSERT, UPDATE ON audit.audit_anchor TO estimator_audit_purge",
]

DOWNGRADE = [
    "DROP FUNCTION audit.ensure_partitions(integer)",
    "DROP FUNCTION audit.append(text, audit.audit_result, uuid, text, inet, text, bytea, text, "
    "text, jsonb)",
    "DROP FUNCTION audit.row_hash(audit.audit_log)",
    "DROP FUNCTION audit.record_json(audit.audit_log)",
    "DROP FUNCTION audit.canonical_json(jsonb)",
    "DROP TABLE audit.audit_anchor",
    "DROP TABLE audit.audit_log",  # вместе с партициями
    "DROP TYPE audit.audit_result",
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
