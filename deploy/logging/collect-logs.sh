#!/usr/bin/env bash
# INF-016 · хранение логов приложения и Nginx 90 дней (SPEC NFR-REL-06; SEC-PD-01 — IP в логах
# хранится не дольше срока). Запуск — cron раз в сутки (estimator-logs.cron).
#   deploy/logging/collect-logs.sh
# Забирает логи контейнеров стенда за прошедшие сутки (api, worker, beat, nginx, postgres, redis,
# clamav) в архив LOG_DIR/ГГГГ-ММ-ДД.log.gz (права 0640) и удаляет архивы старше
# LOG_RETENTION_DAYS (по умолчанию 90). Сами контейнеры держат не больше 5 × 50 МБ на сервис
# (драйвер local, docker-compose.yml). В логах нет паролей, токенов и cookie (SEC-AUTH-04,
# SEC-009) — это проверяет CL-11.
set -euo pipefail
# shellcheck source=../backup/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../backup/lib.sh"

LOG_DIR="${LOG_DIR:-/var/log/estimator}"
KEEP_DAYS="${LOG_RETENTION_DAYS:-90}"
SERVICES=(api worker beat nginx postgres redis clamav)

day="$(date -u -d yesterday +%Y-%m-%d)"
since="${day}T00:00:00Z" until="$(date -u +%Y-%m-%d)T00:00:00Z"
mkdir -p "$LOG_DIR"
chmod 0750 "$LOG_DIR"
target="$LOG_DIR/$day.log.gz"
if [[ -e "$target" ]]; then
  log "архив за $day уже есть"
else
  umask 027
  "${COMPOSE[@]}" logs --no-color --timestamps --since "$since" --until "$until" "${SERVICES[@]}" \
    | gzip -9 >"$target.part"
  mv "$target.part" "$target"
  log "логи за $day: $target ($(du -h "$target" | cut -f1))"
fi
removed="$(find "$LOG_DIR" -maxdepth 1 -name '*.log.gz' -mtime +"$KEEP_DAYS" -print -delete | wc -l)"
log "удалено архивов старше $KEEP_DAYS дней: $removed"
