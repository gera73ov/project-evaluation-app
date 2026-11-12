#!/usr/bin/env bash
# INF-013 · имитация сбоев на работающем стенде test и проверка, что правила 18.4 срабатывают в
# настоящем Prometheus на настоящих метриках приложения (deploy/monitoring/alerts.yml).
#   deploy/monitoring/simulate-alerts.sh [ОТЧЁТ.md]
# Запуск из рабочей копии, где уже поднят стенд профиля test (`make up-test` или
# deploy/home-stand/e2e-stand.sh up). Скрипт поднимает Prometheus (профиль monitoring) с теми же
# правилами, но без задержки `for:` — её проверяет `promtool test rules` (alerts.test.yml), а
# здесь важно, что выражения ловят настоящий сбой. Затем по очереди: вызывает сбой, ждёт
# срабатывания, убирает сбой, где это нужно, ждёт снятия. Цепочка аудита портится последней:
# после прогона стенд нужно пересоздать (cleanup). Работает только на test, не на stage и prod.
# shellcheck disable=SC2329  # функции сбоев вызываются через check по имени
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
REPORT="${1:-$ROOT/stand-logs/alerts-report.md}"
WAIT="${ALERT_WAIT_SECONDS:-240}"   # датчики обновляются раз в 60 с, опрос и правила — раз в 15 с
PROM="http://127.0.0.1:${PROMETHEUS_PORT:-9090}"
RULES="$(mktemp -d)/alerts.yml"
export ALERTS_SIM_RULES="$RULES"
COMPOSE=(docker compose --env-file "$ROOT/.env" -f deploy/compose/docker-compose.yml
         -f deploy/compose/docker-compose.test.yml -f deploy/monitoring/docker-compose.alerts-sim.yml
         --profile test --profile monitoring)
# backup.sh и verify-restore.sh берут файлы compose из окружения (как ops-suite)
export COMPOSE_FILES="$ROOT/deploy/compose/docker-compose.yml $ROOT/deploy/compose/docker-compose.test.yml"
export COMPOSE_PROFILES=test

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
[[ "$(sed -n 's/^APP_ENV=//p' .env | tail -1)" =~ ^(dev|test)$ ]] \
  || { echo "только для стенда test: скрипт портит журнал аудита"; exit 2; }

# --- Prometheus с правилами без for: ------------------------------------------------------------
# строки «for: …» у правил — единственное отличие от alerts.yml
sed -E '/^[[:space:]]+for:[[:space:]]/d' deploy/monitoring/alerts.yml >"$RULES"
chmod 644 "$RULES"
chmod 755 "$(dirname "$RULES")"
log "Prometheus с правилами без задержки for:"
"${COMPOSE[@]}" up -d --wait prometheus

state() { # state ПРАВИЛО [МЕТКА=ЗНАЧЕНИЕ] → firing | pending | inactive
  curl -fsS "$PROM/api/v1/alerts" | python3 -c '
import json, sys
name, label = sys.argv[1], sys.argv[2]
key, _, value = label.partition("=")
states = {
    a["state"] for a in json.load(sys.stdin)["data"]["alerts"]
    if a["labels"].get("alertname") == name and (not key or a["labels"].get(key) == value)
}
print("firing" if "firing" in states else "pending" if "pending" in states else "inactive")' "$1" "${2:-}"
}

wait_for() { # wait_for ПРАВИЛО firing|inactive [МЕТКА=ЗНАЧЕНИЕ] → секунды или пусто
  local name="$1" want="$2" label="${3:-}" started=$SECONDS
  while ((SECONDS - started < WAIT)); do
    [[ "$(state "$name" "$label")" == "$want" ]] && { echo $((SECONDS - started)); return 0; }
    sleep 5
  done
  return 1
}

rc=0
mkdir -p "$(dirname "$REPORT")"
{
  echo "## Имитация оповещений 18.4 (INF-013)"
  echo
  echo "Стенд test, $(date -u +'%Y-%m-%d %H:%M') UTC. Правила alerts.yml без задержки for:, ожидание до $WAIT с."
  echo
  echo "| Правило | Сбой | Сработало | Снято |"
  echo "|---|---|---|---|"
} >"$REPORT"

check() { # check ПРАВИЛО "описание" ФУНКЦИЯ_СБОЯ [ФУНКЦИЯ_ВОССТАНОВЛЕНИЯ]
  local name="$1" what="$2" fire="$3" heal="${4:-}" t_fire="✘" t_heal="—" s
  log "$name: $what"
  # до сбоя правило не должно гореть, иначе «сработало» ничего не доказывает (копий нет — исключение)
  if [[ "$fire" != noop && "$(state "$name")" != inactive ]]; then
    echo "| $name | $what | ✘ горело ещё до сбоя | — |" >>"$REPORT"; rc=1; return 0
  fi
  "$fire" || log "$name: шаг сбоя завершился с ошибкой (продолжаю, проверяю правило)"
  if s=$(wait_for "$name" firing); then t_fire="✔ за $s с"; else rc=1; log "$name: НЕ сработало"; fi
  if [[ -n "$heal" ]]; then
    "$heal" || log "$name: шаг восстановления завершился с ошибкой"
    if s=$(wait_for "$name" inactive); then t_heal="✔ за $s с"; else t_heal="✘"; rc=1; log "$name: НЕ снялось"; fi
  fi
  echo "| $name | $what | $t_fire | $t_heal |" >>"$REPORT"
}

api_curl() { curl -sk -o /dev/null -w '%{http_code}\n' -m 10 "$@"; }
port="$(sed -n 's/^HTTPS_PORT=//p' .env | tail -1)"
BASE="https://localhost:${port:-8443}"

# --- сценарии ----------------------------------------------------------------------------------
noop() { :; }
backup_now() { deploy/backup/backup.sh; }
check EstimatorBackupStale "копий ещё не было" noop backup_now

login_burst() {
  local i
  # Ряд счётчика появляется при первом неуспешном входе, а increase() не видит рост от «ряда ещё
  # нет» до первого значения. Сначала один вход и ожидание опроса — дальше рост считается целиком.
  api_curl -X POST -H 'Content-Type: application/json' \
    -d '{"login":"sim.warmup","password":"wrong"}' "$BASE/api/v1/auth/login" >/dev/null
  sleep 45
  for i in $(seq 1 70); do
    api_curl -X POST -H 'Content-Type: application/json' \
      -d "{\"login\":\"sim.nobody$i\",\"password\":\"wrong-$i\"}" "$BASE/api/v1/auth/login" >/dev/null
  done
}
check EstimatorLoginFailuresBurst "70 неверных входов подряд" login_burst
{
  echo
  echo "Ряды estimator_auth_login_failures_total после серии входов:"
  echo
  echo '```'
  curl -fsS "$PROM/api/v1/query" --data-urlencode 'query=estimator_auth_login_failures_total' \
    | python3 -c 'import json,sys; [print(r["metric"], r["value"][1]) for r in json.load(sys.stdin)["data"]["result"]]' || true
  echo '```'
  echo
} >"$REPORT.login"

clamav_stop() { "${COMPOSE[@]}" stop clamav; }
clamav_start() { "${COMPOSE[@]}" start clamav; }
check EstimatorClamavDown "остановлен ClamAV" clamav_stop clamav_start

db_stop() {
  "${COMPOSE[@]}" stop postgres
  local i
  # запросы во время сбоя: вход без БД отвечает 5xx
  for i in $(seq 1 40); do
    api_curl -X POST -H 'Content-Type: application/json' \
      -d '{"login":"demo.petrov","password":"x"}' "$BASE/api/v1/auth/login" >/dev/null
    sleep 1
  done
}
db_start() { "${COMPOSE[@]}" start postgres && "${COMPOSE[@]}" up -d --wait postgres api; }
# 5xx и «БД красная» — один сбой: сначала ждём оба правила, потом поднимаем БД
db_stop
# на test SMTP не настроен, поэтому EstimatorComponentDown для smtp горит всегда: смотрим db
for pair in Estimator5xxRatioHigh: EstimatorComponentDown:component=db; do
  name="${pair%%:*}" label="${pair#*:}"
  if s=$(wait_for "$name" firing "$label"); then
    echo "| $name | остановлена PostgreSQL, 40 входов за время сбоя | ✔ за $s с | — |" >>"$REPORT"
  else
    rc=1
    echo "| $name | остановлена PostgreSQL, 40 входов за время сбоя | ✘ | — |" >>"$REPORT"
  fi
done
db_start
if s=$(wait_for EstimatorComponentDown inactive component=db); then
  echo "| EstimatorComponentDown | PostgreSQL снова запущена | — | ✔ за $s с |" >>"$REPORT"
else
  rc=1; echo "| EstimatorComponentDown | PostgreSQL снова запущена | — | ✘ |" >>"$REPORT"
fi

audit_tamper() {
  "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U estimator -d estimator -c \
    "SET session_replication_role = replica; UPDATE audit.audit_log SET user_agent = 'simulate-alerts' WHERE id = (SELECT min(id) FROM audit.audit_log);"
  # проверка цепочки найдёт подмену и запишет результат для датчика (exit 1 здесь ожидаем)
  "${COMPOSE[@]}" run --rm --no-deps -T api estimator audit verify || true
}
check EstimatorAuditChainBroken "изменена запись журнала аудита в обход приложения" audit_tamper

{
  echo
  echo "Не имитировались на стенде (проверены только promtool test rules в CI): EstimatorAdCheckStale и"
  echo "EstimatorAdDailySyncStale (стенд в локальном режиме входа), EstimatorWalArchiveLag,"
  echo "EstimatorCertificateExpiring, EstimatorSiemQueueOverflow, EstimatorClamavDbOld, EstimatorApiLatencyP95High,"
  echo "EstimatorWsDeliveryP95High (их пороги проверяет нагрузочный тест QA-019)."
  echo
  echo "После прогона журнал аудита стенда испорчен намеренно: стенд пересоздаётся."
  cat "$REPORT.login" 2>/dev/null || true
} >>"$REPORT"
cat "$REPORT"
exit "$rc"
