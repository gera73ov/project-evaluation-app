#!/usr/bin/env bash
# INF-018 · шаги workflow .github/workflows/e2e-stand.yml на домашнем стенде.
# Запуск из корня репозитория (или из любого его подкаталога) под пользователем stand:
#   deploy/home-stand/e2e-stand.sh up            — образы и весь стенд профиля test (make up-test)
#   deploy/home-stand/e2e-stand.sh seed-env      — печатает export E2E_* для Playwright
#   deploy/home-stand/e2e-stand.sh check-browser — хватает ли системных библиотек Chromium
#   deploy/home-stand/e2e-stand.sh ad-suite      — наборы AD на Samba (QA-012), если они уже есть
#   deploy/home-stand/e2e-stand.sh logs          — логи и состояние контейнеров в $LOGS_DIR
#   deploy/home-stand/e2e-stand.sh cleanup       — остановить стенд, удалить данные и старые образы
# Руками на стенде то же самое: `make up-test`, затем в e2e/ `source <(../deploy/home-stand/e2e-stand.sh
# seed-env) && npx playwright test`, в конце `cleanup`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PROJECT=estimator   # name: в deploy/compose/docker-compose.yml
COMPOSE=(docker compose --env-file "$ROOT/.env" -f "$ROOT/deploy/compose/docker-compose.yml"
         -f "$ROOT/deploy/compose/docker-compose.test.yml" --profile test)
LOGS_DIR="${LOGS_DIR:-$ROOT/stand-logs}"

ensure_env() {
  python3 deploy/compose/make_env.py >/dev/null
  mkdir -p deploy/compose/certs
}

cmd_up() {
  ensure_env
  make up-test
  "${COMPOSE[@]}" ps
}

# Сиды и наполнение узлами (perf/fill.py) идут одноразовым контейнером из образа api: те же
# DATABASE_URL и ENCRYPTION_KEY, что у API, каталог e2e подключается только на чтение.
# Сценарии вызывают эти команды из каталога backend (global-setup.ts → runJson).
cmd_seed_env() {
  local run
  run="$(printf '%q ' "${COMPOSE[@]}" run --rm --no-deps -T -v "$ROOT/e2e:/e2e:ro" api python)"
  local port
  port="$(sed -n 's/^HTTPS_PORT=//p' "$ROOT/.env" | tail -1)"
  printf 'export E2E_BASE_URL=%q\n' "https://localhost:${port:-8443}"
  # FE-094 (e2e/ad): установка с нуля на Samba AD — сброс базы, пароль тестовых учёток каталога, УЦ
  printf 'export E2E_AD=1\n'
  printf 'export E2E_AD_RESET_CMD=%q\n' "${run}/e2e/ad/reset.py"
  printf 'export E2E_AD_PASSWORD=%q\n' "$(sed -n 's/^SAMBA_TEST_PASSWORD=//p' "$ROOT/.env" | tail -1)"
  printf 'export E2E_AD_CA=%q\n' "$ROOT/deploy/compose/certs/ca.crt"
  local name script
  for pair in SEED:auth/seed.py WORK_SEED:work/seed.py ADMIN_SEED:admin/seed.py \
              STATS_SEED:stats/seed.py STATS_FILL:perf/fill.py A11Y_SEED:a11y/seed.py \
              A11Y_FILL:perf/fill.py DISCUSSIONS_SEED:discussions/seed.py \
              DISCUSSIONS_FILL:perf/fill.py SYSTEM_SEED:system/seed.py \
              PERF_SEED:perf/seed.py PERF_FILL:perf/fill.py; do
    name="${pair%%:*}" script="${pair#*:}"
    printf 'export E2E_%s_CMD=%q\n' "$name" "${run}/e2e/${script}"
  done
}

# У stand нет sudo, поэтому `playwright install --with-deps` недоступен. На Linux Mint с рабочим
# столом библиотеки Chromium обычно уже стоят; если нет — понятная ошибка вместо падения браузера.
cmd_check_browser() {
  local bins missing=""
  bins="$(find "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" -type f \
          \( -name chrome-headless-shell -o -name chrome \) -perm -u+x 2>/dev/null || true)"
  [[ -n "$bins" ]] || { echo "::error::Chromium Playwright не найден"; exit 1; }
  while read -r bin; do
    missing+="$(ldd "$bin" 2>/dev/null | awk '/not found/ {print $1}')"$'\n'
  done <<<"$bins"
  missing="$(sort -u <<<"$missing" | sed '/^$/d')"
  if [[ -n "$missing" ]]; then
    echo "::error::Chromium не хватает системных библиотек: $(tr '\n' ' ' <<<"$missing")"
    echo "Установить их из своей учётки (не stand): sudo apt install <пакеты с этими библиотеками>"
    exit 1
  fi
  echo "Библиотеки Chromium на месте"
}

# QA-012 добавит в Makefile цель test-ad (backend/tests/integration/ad, steps/ad_*.py на Samba).
# До тех пор шаг ничего не делает и пишет об этом в сводку прогона.
cmd_ad_suite() {
  if grep -q '^test-ad:' Makefile; then
    make test-ad
  else
    echo "::notice::Наборы AD на Samba (QA-012) ещё не написаны: в Makefile нет цели test-ad"
  fi
}

cmd_logs() {
  [[ -f .env ]] || { echo "стенд не поднимался"; return 0; }
  mkdir -p "$LOGS_DIR"
  "${COMPOSE[@]}" ps -a >"$LOGS_DIR/ps.txt" 2>&1 || true
  "${COMPOSE[@]}" logs --no-color --timestamps >"$LOGS_DIR/compose.log" 2>&1 || true
  docker system df >"$LOGS_DIR/docker-df.txt" 2>&1 || true
  df -h / >"$LOGS_DIR/disk.txt" 2>&1 || true
}

# Тома с данными удаляются, том clamdb остаётся: иначе ClamAV каждый прогон заново качает
# сигнатуры (~300 МБ, зеркала ограничивают частые загрузки). Кэш сборки старше недели — тоже.
cmd_cleanup() {
  ensure_env
  "${COMPOSE[@]}" down --remove-orphans --timeout 20 || true
  docker volume ls -q --filter "label=com.docker.compose.project=${PROJECT}" \
    | grep -v "_clamdb$" | xargs -r docker volume rm || true
  docker image prune -f >/dev/null || true
  docker builder prune -f --filter until=168h >/dev/null || true
  df -h / | tail -1
}

case "${1:-}" in
  up) cmd_up ;;
  seed-env) cmd_seed_env ;;
  check-browser) cmd_check_browser ;;
  ad-suite) cmd_ad_suite ;;
  logs) cmd_logs ;;
  cleanup) cmd_cleanup ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
