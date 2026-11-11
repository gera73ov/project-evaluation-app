# shellcheck shell=bash
# INF-015 · общее для upgrade.sh и rollback.sh (подключается через source).
# shellcheck source=../backup/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../backup/lib.sh"

# Записать APP_VERSION в .env стенда (тег образов api, nginx, postgres)
set_version() {
  local version="$1"
  if grep -q '^APP_VERSION=' "$ENV_FILE"; then
    sed -i "s/^APP_VERSION=.*/APP_VERSION=${version}/" "$ENV_FILE"
  else
    printf 'APP_VERSION=%s\n' "$version" >>"$ENV_FILE"
  fi
}

current_version() { sed -n 's/^APP_VERSION=//p' "$ENV_FILE" | tail -1; }

# Ждать, пока контейнер станет healthy (healthcheck образа api — /health/ready)
wait_healthy() {
  local id="$1" deadline=$((SECONDS + ${HEALTH_TIMEOUT:-180})) state
  while ((SECONDS < deadline)); do
    state="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)"
    [[ "$state" == healthy ]] && return 0
    [[ "$state" == unhealthy || "$state" == missing ]] && break
    sleep 3
  done
  die "контейнер $id не стал healthy (состояние: ${state:-?})"
}

# Поочерёдный перезапуск api (SPEC 18.3 шаг 4): новые реплики на новом образе поднимаются рядом
# со старыми, Nginx перечитывает адреса, старые реплики останавливаются (uvicorn дорабатывает
# начатые запросы, клиенты WebSocket переподключаются и догружают изменения по since).
rolling_restart_api() {
  local old new count
  mapfile -t old < <("${COMPOSE[@]}" ps -q api)
  count=${#old[@]}
  ((count > 0)) || { "${COMPOSE[@]}" up -d --no-deps --wait api; return; }
  log "api: поднимаю $count новых реплик рядом со старыми"
  "${COMPOSE[@]}" up -d --no-deps --no-recreate --scale "api=$((count * 2))" api
  mapfile -t new < <(comm -13 <(printf '%s\n' "${old[@]}" | sort) \
    <("${COMPOSE[@]}" ps -q api | sort))
  for id in "${new[@]}"; do wait_healthy "$id"; done
  "${COMPOSE[@]}" exec -T nginx nginx -s reload
  log "api: останавливаю старые реплики"
  for id in "${old[@]}"; do
    docker stop --time 30 "$id" >/dev/null
    docker rm "$id" >/dev/null
  done
  "${COMPOSE[@]}" exec -T nginx nginx -s reload
  # worker и beat держат только фоновые задачи — их можно перезапустить сразу
  "${COMPOSE[@]}" up -d --no-deps --wait worker beat
}

check_ready() {
  local id
  id="$("${COMPOSE[@]}" ps -q api | head -1)"
  docker exec "$id" python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status != 200)" \
    || die "/health/ready не зелёный"
  log "/health/ready зелёный"
}
