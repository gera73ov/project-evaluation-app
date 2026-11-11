#!/usr/bin/env bash
# INF-015 · обновление приложения (SPEC 18.3, NFR-MNT-02).
#   deploy/scripts/upgrade.sh ВЕРСИЯ [--build]
# Шаги 18.3: (1) резервная копия → (2) образы новой версии (docker compose pull; --build —
# собрать из рабочей копии, для test) → (3) estimator migrate (миграции expand совместимы с
# прежней версией кода) → (4) поочерёдный перезапуск api, затем worker и beat → (5) /health/ready.
# Прежняя версия печатается в конце: она нужна для rollback.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

version="${1:-}"; [[ -n "$version" ]] || { sed -n '2,8p' "$0"; exit 2; }
build=0; [[ "${2:-}" == "--build" ]] && build=1
previous="$(current_version)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log "шаг 1: резервная копия перед обновлением ($previous → $version)"
"$(dirname "$0")/../backup/backup.sh"

log "шаг 2: образы версии $version"
set_version "$version"
if ((build)); then "${COMPOSE[@]}" build; else "${COMPOSE[@]}" pull api nginx postgres; fi

log "шаг 3: миграции"
"${COMPOSE[@]}" run --rm migrate

log "шаг 4: поочерёдный перезапуск"
rolling_restart_api
"${COMPOSE[@]}" up -d --no-deps --wait nginx

log "шаг 5: проверка"
check_ready
log "обновлено до $version. Откат: deploy/scripts/rollback.sh $previous [--restore \"$started_at\"]"
