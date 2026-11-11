#!/usr/bin/env bash
# QA-025 · проверка восстановления из резервной копии на тестовом стенде (NFR-REL-02, NFR-REL-03;
# протокол — manuals/operations.md, раздел «Ежеквартальная проверка восстановления»).
# ТОЛЬКО ДЛЯ ТЕСТОВОГО СТЕНДА: имитирует потерю диска БД (том pgdata удаляется).
#   deploy/backup/verify-restore.sh [ПРОТОКОЛ.md]
# Шаги: полная копия → метки-«пробы» в БД до и после копии → ожидание архивации WAL →
# потеря тома БД → restore.sh --wipe → проверка проб, версии схемы и числа строк ключевых таблиц.
# RPO: проба, записанная после полной копии и за archive_timeout до сбоя, должна быть на месте.
# RTO: время restore.sh (цель — не больше 4 часов).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
REPORT="${1:-/dev/stdout}"
WAIT_ARCHIVE="${WAIT_ARCHIVE:-75}"   # больше archive_timeout (60 с)

psql_() { "${COMPOSE[@]}" exec -T postgres psql -U estimator -d estimator -v ON_ERROR_STOP=1 -qtA "$@"; }
counts() {
  psql_ -c "SELECT (SELECT version_num FROM alembic_version) || ' projects=' ||
    (SELECT count(*) FROM projects) || ' nodes=' || (SELECT count(*) FROM nodes) ||
    ' users=' || (SELECT count(*) FROM users)"
}

grep -q '^APP_ENV=prod' "$ENV_FILE" 2>/dev/null && die "verify-restore.sh не запускается на prod"

psql_ -c "CREATE TABLE IF NOT EXISTS public.qa_backup_probe (name text PRIMARY KEY, at timestamptz)"
psql_ -c "INSERT INTO qa_backup_probe VALUES ('before_full', now()) ON CONFLICT (name) DO UPDATE SET at = now()"
"$(dirname "$0")/backup.sh"
psql_ -c "INSERT INTO qa_backup_probe VALUES ('after_full', now()) ON CONFLICT (name) DO UPDATE SET at = now()"
before="$(counts)"
log "жду архивации WAL ${WAIT_ARCHIVE} с"
sleep "$WAIT_ARCHIVE"
crash_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
last_wal="$(psql_ -c "SELECT coalesce(to_char(last_archived_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), '-') FROM pg_stat_archiver")"

started=$(date +%s)
"$(dirname "$0")/restore.sh" --wipe
rto=$(( $(date +%s) - started ))
after="$(counts)"
probes="$(psql_ -c "SELECT string_agg(name, ',' ORDER BY name) FROM qa_backup_probe")"
psql_ -c "DROP TABLE qa_backup_probe"

ok=1
[[ "$probes" == "after_full,before_full" ]] || ok=0
[[ "$before" == "$after" ]] || ok=0
(( rto <= 4 * 3600 )) || ok=0
{
  echo "## Проверка восстановления $(date -u +%Y-%m-%d)"
  echo
  echo "| Показатель | Значение |"
  echo "|---|---|"
  echo "| Сбой (потеря тома БД) | $crash_at |"
  echo "| Последний WAL в архиве до сбоя | $last_wal |"
  echo "| Пробы после восстановления | $probes (ожидались after_full,before_full) |"
  echo "| Данные до / после | \`$before\` / \`$after\` |"
  echo "| RTO (restore.sh) | ${rto} с (цель ≤ 4 ч) |"
  echo "| RPO | данные за archive_timeout (60 с) до сбоя сохранены: $([[ $probes == *after_full* ]] && echo да || echo нет) (цель ≤ 15 мин) |"
  echo "| Итог | $( ((ok)) && echo 'УСПЕХ' || echo 'ПРОВАЛ') |"
} >"$REPORT"
((ok)) || die "восстановление не прошло проверку (см. протокол)"
log "восстановление проверено: RTO ${rto} с"
