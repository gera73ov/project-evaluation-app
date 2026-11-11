# shellcheck shell=bash
# INF-012 · общее для backup.sh, restore.sh и verify-restore.sh (подключается через source).
# COMPOSE_FILES — файлы compose стенда через пробел (по умолчанию — базовый файл репозитория);
# на stage и prod служба эксплуатации задаёт свои (deploy/envs/<стенд>/…).
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
COMPOSE_FILES="${COMPOSE_FILES:-$ROOT/deploy/compose/docker-compose.yml}"
COMPOSE=(docker compose --env-file "$ENV_FILE")
for f in $COMPOSE_FILES; do COMPOSE+=(-f "$f"); done
STANZA=estimator
# shellcheck disable=SC2034 # используется в restore.sh
PROJECT="${COMPOSE_PROJECT_NAME:-estimator}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ОШИБКА: $*" >&2; exit 1; }

# pgBackRest внутри контейнера postgres от пользователя postgres
pgbr() { "${COMPOSE[@]}" exec -T -u postgres postgres pgbackrest --stanza="$STANZA" "$@"; }
