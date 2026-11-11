#!/usr/bin/env bash
# INF-012 · ежедневная резервная копия (SPEC 18.2, NFR-REL-02, NFR-REL-06; запуск — cron, 01:00).
#   deploy/backup/backup.sh            — полная копия БД, копия тома документов, чистка старше 30 дней
#   deploy/backup/backup.sh --check    — только проверить архивацию WAL (pgbackrest check)
# Между полными копиями WAL уходит в репозиторий непрерывно (archive_command, archive_timeout
# 60 с), поэтому потеря при восстановлении — не больше нескольких минут (RPO ≤ 15 минут).
# При успехе пишет время в файл-метку тома backupmark — её показывает «Состояние системы»
# (FR-SA-07) и проверяет оповещение «бэкап старше 26 часов» (18.4).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
MARKER=/var/lib/estimator/backup/last-success

# stanza создаётся один раз; повторный вызов на той же базе ничего не меняет
pgbr stanza-create >/dev/null
pgbr check
[[ "${1:-}" == "--check" ]] && exit 0

log "полная копия БД"
pgbr --type=full backup
pgbr expire   # полные копии старше repo1-retention-full (30 дней) и их WAL

# Документы заказчика на томе уже зашифрованы (AES-256-GCM, ключи — в БД под мастер-ключом,
# SEC-CRYPT-06), поэтому архив тома копируется как есть. Выгрузки живут 24 часа — не копируются.
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log "копия тома документов"
# Том documents подключён к контейнеру postgres только на чтение (docker-compose.yml); каталог
# принадлежит пользователю api (0750), поэтому архив делает root контейнера.
"${COMPOSE[@]}" exec -T -u 0 postgres sh -ec "
  install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest/documents
  tar -C /data -cf /var/lib/pgbackrest/documents/documents-$stamp.tar documents
  chown postgres:postgres /var/lib/pgbackrest/documents/documents-$stamp.tar
  find /var/lib/pgbackrest/documents -name 'documents-*.tar' -mtime +$KEEP_DAYS -delete
"

"${COMPOSE[@]}" exec -T -u postgres postgres sh -ec "umask 022; date -u +%Y-%m-%dT%H:%M:%SZ > $MARKER"
log "копия готова"
pgbr info
