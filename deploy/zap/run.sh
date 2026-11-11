#!/usr/bin/env bash
# QA-021 · DAST OWASP ZAP на стенде (deploy/zap/README.md; SPEC SEC-SDLC-02, SEC-SDLC-05, 17.3).
#   deploy/zap/run.sh            — стенд из этой рабочей копии (.env в корне), отчёты в deploy/zap/report
# Шаги:
#   1. baseline: пассивное сканирование сайта без входа (паук по страницам и статике);
#   2. сессии эксперта, модератора и администратора (prepare.py sessions, контейнер api) и копия
#      OpenAPI без операций выхода и смены входа (prepare.py openapi);
#   3. авторизованное сканирование API по OpenAPI для каждой роли (zap-api-scan, активные правила);
#   4. итог: число находок по уровням риска; код выхода 1, если есть High.
# Переменные: ZAP_TARGET (адрес стенда; по умолчанию https://localhost:HTTPS_PORT), ZAP_ROLES
# ("expert moderator admin"), ZAP_IMAGE, ZAP_OUT (deploy/zap/report), ZAP_MAX_MINUTES (10 на роль),
# ZAP_MARK_SETUP=1 — отметить мастер первичной настройки завершённым (одноразовый стенд).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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

IMAGE="${ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy:2.17.0@sha256:9624669db72f54d86c4b46a7064518bd9bf79d8c61a4c31befa9923489f328af}"
target="${ZAP_TARGET:-https://localhost:$(env_value HTTPS_PORT | grep . || echo 443)}"
out="${ZAP_OUT:-$ROOT/deploy/zap/report}"
minutes="${ZAP_MAX_MINUTES:-10}"
mkdir -p "$out"
chmod 0777 "$out"  # ZAP в контейнере пишет отчёты пользователем zap (uid 1000)
cp deploy/zap/rules.tsv "$out/rules.tsv"  # -c читается из /zap/wrk
sessions="$(mktemp)"
trap 'rm -f "$sessions"' EXIT

prepare() {
  compose run --rm --no-deps -T -v "$ROOT/deploy/zap:/zap-cfg:ro" -v "$ROOT/contracts:/contracts:ro" \
    api python /zap-cfg/prepare.py "$@"
}

# Сеть хоста: адрес стенда тот же, что с самого сервера. Сертификат стенда ZAP не проверяет.
zap() {
  docker run --rm --network host -v "$out:/zap/wrk:rw" "$@"
}

rc=0
echo "baseline: $target"
zap "$IMAGE" zap-baseline.py -t "$target" -c rules.tsv -m "$minutes" -I \
  -r baseline.html -J baseline.json || rc=$?
((rc <= 2)) || { echo "ZAP baseline завершился с ошибкой $rc" >&2; exit 1; }

prepare openapi /contracts/openapi.yaml "$target" >"$out/openapi.yaml"
if [[ "${ZAP_MARK_SETUP:-0}" == 1 ]]; then prepare sessions --mark-setup >"$sessions"; else prepare sessions >"$sessions"; fi

for role in ${ZAP_ROLES:-expert moderator admin}; do
  sid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["roles"][sys.argv[2]]["session"])' "$sessions" "$role")"
  csrf="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["roles"][sys.argv[2]]["csrf"])' "$sessions" "$role")"
  echo "API с сессией роли $role"
  rc=0
  # Cookie сессии — ZAP_AUTH_HEADER (во все запросы), CSRF-токен — правилом подмены заголовка.
  # Два потока: лимит 300 изменяющих запросов в минуту на пользователя (SEC-WEB-07).
  zap -e ZAP_AUTH_HEADER=Cookie -e ZAP_AUTH_HEADER_VALUE="__Host-session=$sid" \
    "$IMAGE" zap-api-scan.py -t /zap/wrk/openapi.yaml -f openapi -c rules.tsv -I \
    -r "api-$role.html" -J "api-$role.json" -z "\
-config scanner.threadPerHost=2 \
-config scanner.maxScanDurationInMins=$minutes \
-config replacer.full_list(0).description=csrf \
-config replacer.full_list(0).enabled=true \
-config replacer.full_list(0).matchtype=REQ_HEADER \
-config replacer.full_list(0).matchstr=X-CSRF-Token \
-config replacer.full_list(0).regex=false \
-config replacer.full_list(0).replacement=$csrf" || rc=$?
  ((rc <= 2)) || { echo "ZAP API ($role) завершился с ошибкой $rc" >&2; exit 1; }
done

status=0
# Итог по отчётам JSON: riskcode 3 — High, 2 — Medium, 1 — Low, 0 — Informational
if python3 - "$out" <<'PY' | tee "$out/verdict.txt"
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
names = {"3": "High", "2": "Medium", "1": "Low", "0": "Info"}
high = 0
for report in sorted(out.glob("*.json")):
    counts = {k: 0 for k in names}
    for site in json.loads(report.read_text()).get("site", []):
        for alert in site.get("alerts", []):
            counts[alert["riskcode"]] += 1
            if alert["riskcode"] == "3":
                high += 1
                print(f"  HIGH {report.stem}: {alert['alert']} ({alert['pluginid']})")
    print(f"QA-021 {report.stem}: " + ", ".join(f"{names[k]} {v}" for k, v in counts.items()))
print("QA-021: " + ("есть находки High — порог 17.3 не выполнен" if high else "находок High нет"))
sys.exit(1 if high else 0)
PY
then :; else status=1; fi
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  { echo '## OWASP ZAP (QA-021)'; echo; sed 's/^/    /' "$out/verdict.txt"; } >>"$GITHUB_STEP_SUMMARY"
fi
exit "$status"
