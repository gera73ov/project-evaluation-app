#!/usr/bin/env bash
# INF-015 · откат обновления (SPEC 18.3, NFR-MNT-02).
#   deploy/scripts/rollback.sh ПРЕЖНЯЯ_ВЕРСИЯ                       — прежний тег образов
#   deploy/scripts/rollback.sh ПРЕЖНЯЯ_ВЕРСИЯ --downgrade РЕВИЗИЯ  — и alembic downgrade до ревизии
#   deploy/scripts/rollback.sh ПРЕЖНЯЯ_ВЕРСИЯ --restore "ВРЕМЯ"     — и восстановление БД на момент
#                                                                     перед обновлением (крайний случай)
# Обычно хватает первого варианта: миграции expand совместимы с прежней версией кода (проверка
# CI «старый код на новой схеме»). downgrade — если новая схема мешает прежнему коду; restore —
# если данные испорчены (правки после ВРЕМЕНИ теряются, решение — за владельцем продукта).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

version="${1:-}"; [[ -n "$version" ]] || { sed -n '2,10p' "$0"; exit 2; }
shift
downgrade="" restore=""
while (($#)); do
  case "$1" in
    --downgrade) downgrade="$2"; shift 2 ;;
    --restore) restore="$2"; shift 2 ;;
    *) sed -n '2,10p' "$0"; exit 2 ;;
  esac
done

if [[ -n "$downgrade" ]]; then
  # downgrade делает код новой версии: он знает свои миграции
  log "alembic downgrade до $downgrade (кодом текущей версии $(current_version))"
  "${COMPOSE[@]}" run --rm --no-deps migrate estimator migrate --downgrade "$downgrade"
fi

log "образы версии $version"
set_version "$version"
"${COMPOSE[@]}" pull api nginx postgres || log "pull не удался — использую локальные образы $version"

if [[ -n "$restore" ]]; then
  log "восстановление БД на $restore"
  "$(dirname "$0")/../backup/restore.sh" --time "$restore"
else
  rolling_restart_api
  "${COMPOSE[@]}" up -d --no-deps --wait nginx
fi
check_ready
log "откат на $version выполнен"
