#!/usr/bin/env bash
# INF-009 · проверка конфигурации Nginx в Docker: TLS только 1.2/1.3, 301 с HTTP, заголовки
# безопасности на статике, index.html (CSP с nonce), ошибках Nginx (404, 413, 503), лимиты тела
# по location, /health и /metrics не отдаются, nonce новый на каждый ответ, gzip только у дерева.
# Запуск из корня репозитория: deploy/nginx/test_nginx.sh (нужны docker, curl, openssl).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${NGINX_IMAGE:-nginx:1.30-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949}"
NAME="inf009-$$"
WORK="$(mktemp -d)"
HTTPS_PORT="${TEST_HTTPS_PORT:-18443}"
HTTP_PORT="${TEST_HTTP_PORT:-18080}"
FAILED=0

cleanup() {
  docker rm -f "$NAME-nginx" "$NAME-closed" "$NAME-api" >/dev/null 2>&1 || true
  docker network rm "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

check() { # check <описание> <команда…>
  local what="$1"; shift
  if "$@"; then echo "ok   $what"; else echo "FAIL $what"; FAILED=1; fi
}
has_header() { grep -qi "^$2: $3" "$1"; }

# Сертификат и статика как в образе: index.html с заглушкой nonce и один файл сборки
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=localhost" \
  -keyout "$WORK/server.key" -out "$WORK/server.crt" 2>/dev/null
chmod 644 "$WORK/server.key"
mkdir -p "$WORK/html/assets"
cp "$ROOT/frontend/index.html" "$WORK/html/index.html"
echo "console.log(1)" > "$WORK/html/assets/app-abc123.js"
# INF-011: каталог списков сетей стенда; на dev пуст — пускают всех
mkdir -p "$WORK/access" "$WORK/closed"
echo "deny all;" > "$WORK/closed/stand.conf"

docker network create "$NAME" >/dev/null
docker run -d --name "$NAME-api" --network "$NAME" --network-alias api \
  -v "$ROOT/deploy/nginx/test/api_stub.conf:/etc/nginx/conf.d/default.conf:ro" "$IMAGE" >/dev/null
docker run -d --name "$NAME-nginx" --network "$NAME" --user 101:101 --read-only --tmpfs /tmp \
  -p "127.0.0.1:$HTTPS_PORT:8443" -p "127.0.0.1:$HTTP_PORT:8080" \
  -v "$ROOT/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$ROOT/deploy/nginx/log_format.conf:/etc/nginx/log_format.conf:ro" \
  -v "$ROOT/deploy/nginx/conf.d:/etc/nginx/conf.d:ro" \
  -v "$ROOT/deploy/nginx/snippets:/etc/nginx/snippets:ro" \
  -v "$WORK/server.crt:/etc/nginx/certs/server.crt:ro" \
  -v "$WORK/server.key:/etc/nginx/certs/server.key:ro" \
  -v "$WORK/html:/usr/share/nginx/html:ro" \
  -v "$WORK/access:/etc/nginx/access:ro" \
  --entrypoint nginx "$IMAGE" -g "daemon off;" >/dev/null

BASE="https://localhost:$HTTPS_PORT"
for _ in $(seq 1 50); do
  curl -sk -o /dev/null "$BASE/" && break
  sleep 0.2
done

get() { # get <файл заголовков> <путь> [доп. аргументы curl] → тело в stdout
  local headers="$1" path="$2"; shift 2
  curl -sk -D "$headers" "$@" "$BASE$path"
}
security_headers() { # все заголовки SEC-WEB-03 и HSTS
  has_header "$1" strict-transport-security "max-age=31536000; includeSubDomains" &&
    has_header "$1" x-content-type-options nosniff &&
    has_header "$1" referrer-policy same-origin &&
    has_header "$1" permissions-policy "camera=(), microphone=(), geolocation=()" &&
    has_header "$1" cross-origin-opener-policy same-origin
}
status_is() { head -1 "$1" | grep -q " $2"; }

# --- TLS: только 1.2 и 1.3 ---------------------------------------------------------------------
tls_ok() { openssl s_client -connect "127.0.0.1:$HTTPS_PORT" "$@" </dev/null >/dev/null 2>&1; }
tls_refused() { ! tls_ok "$@"; }
check "TLS 1.3 принимается" tls_ok -tls1_3
check "TLS 1.2 принимается" tls_ok -tls1_2
check "TLS 1.1 отклоняется" tls_refused -tls1_1
check "TLS 1.2 без ECDHE (обмен ключами RSA) отклоняется" tls_refused -tls1_2 -cipher AES128-GCM-SHA256
check "TLS 1.2 с CBC отклоняется" tls_refused -tls1_2 -cipher ECDHE-RSA-AES128-SHA

# --- HTTP → 301 ------------------------------------------------------------------------------
curl -s -D "$WORK/h_http" -o /dev/null "http://localhost:$HTTP_PORT/projects?x=1"
check "HTTP отвечает 301" status_is "$WORK/h_http" 301
check "Location — https с тем же путём" has_header "$WORK/h_http" location "https://localhost/projects?x=1"

# --- index.html: CSP с nonce, nonce в meta, новый на каждый ответ ----------------------------
meta_nonce() { grep -o 'name="csp-nonce" content="[^"]*"' "$1" | sed 's/.*content="//; s/"$//'; }
get "$WORK/h_index1" /projects/123 >"$WORK/b_index1"
get "$WORK/h_index2" / >"$WORK/b_index2"
nonce1="$(meta_nonce "$WORK/b_index1")"
nonce2="$(meta_nonce "$WORK/b_index2")"
check "index.html: 200" status_is "$WORK/h_index1" 200
check "index.html: заголовки безопасности" security_headers "$WORK/h_index1"
check "index.html: заглушка заменена на nonce" test -n "$nonce1" -a "$nonce1" != "__CSP_NONCE__"
check "index.html: nonce в CSP совпадает с meta" grep -qi "style-src 'self' 'nonce-$nonce1'" "$WORK/h_index1"
check "index.html: nonce новый на каждый ответ" test "$nonce1" != "$nonce2"
check "index.html: CSP без unsafe-inline" bash -c "! grep -i unsafe-inline '$WORK/h_index1'"
check "index.html: connect-src с wss://<host>" grep -qi "connect-src 'self' wss://localhost;" "$WORK/h_index1"
check "index.html: Cache-Control no-store" has_header "$WORK/h_index1" cache-control no-store
get "$WORK/h_badhost" / -H "Host: evil;script-src *" >/dev/null || true
check "CSP: некорректный Host не попадает в политику" bash -c "! grep -qi 'script-src \*' '$WORK/h_badhost'"

# --- Статика и ошибки Nginx ------------------------------------------------------------------
get "$WORK/h_asset" /assets/app-abc123.js >/dev/null
check "статика: заголовки безопасности" security_headers "$WORK/h_asset"
check "статика: кэш на год" has_header "$WORK/h_asset" cache-control "public, max-age=31536000, immutable"
get "$WORK/h_404" /assets/missing.js >"$WORK/b_404"
check "404 Nginx: статус" status_is "$WORK/h_404" 404
check "404 Nginx: заголовки безопасности" security_headers "$WORK/h_404"
check "404 Nginx: Problem Details" has_header "$WORK/h_404" content-type application/problem+json
check "404 Nginx: code NOT_FOUND и error_id" grep -q '"code":"NOT_FOUND","error_id":"[0-9a-f]\{32\}"' "$WORK/b_404"
for path in /metrics /health/live /health/ready; do
  get "$WORK/h_hidden" "$path" >/dev/null
  check "$path не отдаётся наружу (404)" status_is "$WORK/h_hidden" 404
done

# --- Прокси API и лимиты тела ----------------------------------------------------------------
get "$WORK/h_api" /api/v1/me >"$WORK/b_api"
check "API проксируется с X-Forwarded-Proto и X-Request-ID" grep -q '"proto":"https","request_id":"[0-9a-f]\{32\}"' "$WORK/b_api"
check "API: HSTS добавлен" has_header "$WORK/h_api" strict-transport-security "max-age=31536000; includeSubDomains"
get "$WORK/h_tree" /api/v1/projects/0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e6f/tree \
  -H 'Accept-Encoding: gzip' >"$WORK/b_tree"
check "дерево проекта: ответ сжат gzip" has_header "$WORK/h_tree" content-encoding gzip
check "дерево проекта: тело распаковывается" bash -c "gzip -dc '$WORK/b_tree' | grep -q '\"nodes\"'"
check "дерево проекта: HSTS добавлен" has_header "$WORK/h_tree" strict-transport-security "max-age=31536000; includeSubDomains"
get "$WORK/h_api_gz" /api/v1/me -H 'Accept-Encoding: gzip' >/dev/null
check "остальной API не сжимается (BREACH)" bash -c "! grep -qi '^content-encoding' '$WORK/h_api_gz'"
post_size() { # post_size <путь> <байт> → HTTP-статус; тело и заголовки — в $WORK/b_post, h_post
  head -c "$2" /dev/zero | curl -sk -o "$WORK/b_post" -D "$WORK/h_post" -w '%{http_code}' \
    -X POST -H 'Content-Type: application/octet-stream' --data-binary @- "$BASE$1"
}
limit_case() { # limit_case <путь> <лимит байт>
  local path="$1" limit="$2" code
  code="$(post_size "$path" "$limit")"
  check "$path: $limit байт проходят (получено $code)" test "$code" = 200
  code="$(post_size "$path" $((limit + 1)))"
  check "$path: $((limit + 1)) байт → 413" test "$code" = 413
  check "$path: 413 — PAYLOAD_TOO_LARGE" grep -q '"code":"PAYLOAD_TOO_LARGE"' "$WORK/b_post"
  check "$path: 413 — limit_bytes $limit" grep -q "\"limit_bytes\":$limit}" "$WORK/b_post"
  check "$path: 413 — заголовки безопасности" security_headers "$WORK/h_post"
}
limit_case /api/v1/me 1048576
limit_case /api/v1/system/settings/auth 65536
limit_case /api/v1/admin/calendar 262144
limit_case /api/v1/projects/0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e6f/documents 52428800

# --- INF-011: список сетей стенда — чужой адрес получает 403 и на HTTPS, и на HTTP -----------
# (до остановки api: upstream разрешается при старте Nginx)
docker run -d --name "$NAME-closed" --network "$NAME" --user 101:101 --read-only --tmpfs /tmp \
  -p "127.0.0.1:$((HTTPS_PORT + 1)):8443" -p "127.0.0.1:$((HTTP_PORT + 1)):8080" \
  -v "$ROOT/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$ROOT/deploy/nginx/log_format.conf:/etc/nginx/log_format.conf:ro" \
  -v "$ROOT/deploy/nginx/conf.d:/etc/nginx/conf.d:ro" \
  -v "$ROOT/deploy/nginx/snippets:/etc/nginx/snippets:ro" \
  -v "$WORK/server.crt:/etc/nginx/certs/server.crt:ro" \
  -v "$WORK/server.key:/etc/nginx/certs/server.key:ro" \
  -v "$WORK/html:/usr/share/nginx/html:ro" \
  -v "$WORK/closed:/etc/nginx/access:ro" \
  --entrypoint nginx "$IMAGE" -g "daemon off;" >/dev/null
for _ in $(seq 1 50); do
  curl -sk -o /dev/null "https://localhost:$((HTTPS_PORT + 1))/" && break
  sleep 0.2
done
curl -sk -D "$WORK/h_closed" -o /dev/null "https://localhost:$((HTTPS_PORT + 1))/" || true
curl -s -D "$WORK/h_closed_http" -o /dev/null "http://localhost:$((HTTP_PORT + 1))/" || true
check "сеть вне списка стенда: HTTPS 403" status_is "$WORK/h_closed" 403
check "сеть вне списка стенда: HTTP 403" status_is "$WORK/h_closed_http" 403

# --- API недоступен → 503 Problem Details с заголовками ---------------------------------------
docker stop "$NAME-api" >/dev/null
get "$WORK/h_503" /api/v1/me --max-time 30 >"$WORK/b_503" || true
check "API недоступен: 503" status_is "$WORK/h_503" 503
check "API недоступен: заголовки безопасности" security_headers "$WORK/h_503"
check "API недоступен: SERVICE_UNAVAILABLE" grep -q '"code":"SERVICE_UNAVAILABLE"' "$WORK/b_503"

if [[ $FAILED -ne 0 ]]; then
  docker logs "$NAME-nginx" 2>&1 | tail -20
  echo "INF-009: есть ошибки"
  exit 1
fi
echo "INF-009: все проверки пройдены"
