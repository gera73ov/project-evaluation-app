#!/usr/bin/env bash
# QA-019 · нагрузочный тест стенда по профилю NFR-PERF-01 (load/README.md).
#   load/run.sh                  — стенд из этой рабочей копии (.env в корне), отчёт в load/report
# Шаги: сид load/seed.py одноразовым контейнером api; прогон Locust без интерфейса в контейнере
# из того же образа Python, что у api (зависимости — load/requirements.txt, ставятся при запуске);
# отчёт HTML и CSV. Файл со слотами (действующие сессии) удаляется в конце.
# Переменные: LOAD_HOST (адрес стенда; по умолчанию https://localhost:HTTPS_PORT), LOAD_USERS (50),
# LOAD_PYTHON_IMAGE (образ для Locust; по умолчанию PYTHON_IMAGE из deploy/docker/api.Dockerfile),
# LOAD_SPAWN_RATE (5), LOAD_DURATION (10m), LOAD_NODES (300), LOAD_SEED_ARGS (например
# --mark-setup для одноразового стенда без мастера настройки), LOAD_OUT (load/report),
# LOAD_CA (по умолчанию deploy/compose/certs/ca.crt, если он есть), остальные LOAD_* — locustfile.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || { echo "нет $ENV_FILE: стенд не развёрнут" >&2; exit 1; }
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

compose() {
  local -a cmd=(docker compose --env-file "$ENV_FILE")
  local files f
  files="$(env_value COMPOSE_FILES)"
  files="${files:-deploy/compose/docker-compose.yml deploy/compose/docker-compose.test.yml}"
  for f in ${files//:/ }; do cmd+=(-f "$ROOT/$f"); done
  COMPOSE_PROFILES="$(env_value COMPOSE_PROFILES)" "${cmd[@]}" "$@"
}

out="${LOAD_OUT:-$ROOT/load/report}"
mkdir -p "$out"
slots="$(mktemp "$out/slots.XXXXXX.json")"
trap 'rm -f "$slots"' EXIT

echo "сид: пользователи, проекты, сессии (load/seed.py)"
# shellcheck disable=SC2086  # LOAD_SEED_ARGS — список аргументов
compose run --rm --no-deps -T -v "$ROOT/load:/load:ro" api \
  python /load/seed.py --nodes "${LOAD_NODES:-300}" ${LOAD_SEED_ARGS:-} >"$slots"

host="${LOAD_HOST:-https://localhost:$(env_value HTTPS_PORT | grep . || echo 443)}"
ca="${LOAD_CA:-$ROOT/deploy/compose/certs/ca.crt}"
image="${LOAD_PYTHON_IMAGE:-$(sed -n 's/^ARG PYTHON_IMAGE=//p' deploy/docker/api.Dockerfile)}"
a_env=()
for name in $(compgen -e | grep '^LOAD_' || true); do
  case "$name" in LOAD_SLOTS|LOAD_CA|LOAD_OUT|LOAD_HOST|LOAD_PYTHON_IMAGE) ;; *) a_env+=(-e "$name") ;; esac
done
a_env+=(-e LOAD_SLOTS="/out/$(basename "$slots")" -e LOAD_ORIGIN="${LOAD_ORIGIN:-$(env_value APP_BASE_URL)}")
mounts=(-v "$ROOT/load:/load:ro" -v "$out:/out")
if [[ -s "$ca" ]]; then mounts+=(-v "$ca:/ca.crt:ro"); a_env+=(-e LOAD_CA=/ca.crt); fi

echo "Locust: ${LOAD_USERS:-50} пользователей, ${LOAD_DURATION:-10m}, $host"
rc=0
# Сеть хоста: адрес стенда тот же, что с самого сервера (localhost:HTTPS_PORT)
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp "${a_env[@]}" "${mounts[@]}" \
  "$image" sh -c 'pip install -q --user --no-warn-script-location -r /load/requirements.txt &&
    exec /tmp/.local/bin/locust -f /load/locustfile.py --headless --host "$0" -u "$1" -r "$2" \
      -t "$3" --html /out/report.html --csv /out/load --only-summary' \
  "$host" "${LOAD_USERS:-50}" "${LOAD_SPAWN_RATE:-5}" "${LOAD_DURATION:-10m}" 2>&1 \
  | tee "$out/summary.txt" || rc=$?
grep -h '^QA-019' "$out/summary.txt" >"$out/verdict.txt" || true
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  { echo '## Нагрузочный тест (QA-019)'; echo; sed 's/^/    /' "$out/verdict.txt"; } >>"$GITHUB_STEP_SUMMARY"
fi
exit "$rc"
