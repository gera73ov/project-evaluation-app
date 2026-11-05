# DEC-20261105-db-audit-hash-chain

- **Тип:** решение (DEC), уровень A1
- **Время:** 2026-11-05T15:45:00Z
- **Трек:** DB (задача DB-009); потребители — SEC-004 (`audit verify`, `audit purge`), QA-010
- **Основание:** SPEC SEC-AUD-02, SEC-AUD-03, SEC-AUD-04; contracts/audit-events.yaml раздел 1;
  contracts/db/schema.md 2.6

## Контекст

SEC-AUD-03 требует, чтобы хэш считала функция БД под `pg_advisory_xact_lock`. Контракт задаёт поля
записи и RFC 8785, но не фиксирует, как именно `prev_hash` входит в хэш и как записываются значения
полей. Без единого правила запись (БД) и проверка (`audit verify`, Python) разойдутся.

## Решение

1. Хэш считает БД: `audit.row_hash(r) = SHA-256(prev_hash ‖ UTF-8(canonical_json(record_json(r))))`,
   где `prev_hash` — 32 сырых байта (не hex). Функции — в миграции `backend/alembic/versions/0003_audit.py`.
2. `record_json` — объект с именами полей контракта: `time`, `type`, `result`, `user_id`, `login`,
   `ip`, `user_agent`, `session_hash`, `object_type`, `object_id`, `details`, `prev_hash`.
   Значения: `time` — `YYYY-MM-DDTHH:MM:SS.ffffffZ` (UTC, 6 знаков); `ip` — адрес без маски;
   `session_hash` и `prev_hash` — hex строчными; отсутствующее значение — `null` (ключ есть всегда).
3. Канонический JSON: ключи по возрастанию кодовых точек, разделители `,` и `:` без пробелов,
   не-ASCII символы как есть, управляющие — `\uXXXX` (кроме `\b \f \n \r \t`), числа без лишних нулей
   дробной части. На Python то же даёт
   `json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)` для целых чисел, строк,
   bool, null, списков и объектов — эквивалентность проверяет
   `backend/tests/integration/db/test_audit_log.py::test_hash_matches_reference_implementation`.
4. Первая запись и запись после полного purge: `prev_hash` = `audit.audit_anchor.last_purged_hash`,
   если якорь есть, иначе 32 нулевых байта.
5. Время записи ставит функция (`clock_timestamp()` под блокировкой), а не вызывающий код: порядок
   `id` и `ts` совпадает. `audit.append` требует `READ COMMITTED` (иначе исключение).
6. Ключ блокировки — `418581342580` (`estimator.db.models.audit.AUDIT_LOCK_KEY`); `audit purge` берёт
   тот же ключ, чтобы удаление и запись якоря не пересекались с вставкой.

## Последствия

SEC-004 проверяет цепочку функцией `audit.row_hash` в SQL или своей реализацией на Python по
пунктам 2–3; при расхождении правило меняется новой записью DEC и миграцией, а не правкой этой записи.
