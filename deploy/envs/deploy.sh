#!/usr/bin/env bash
# INF-011 · развёртывание стенда test или stage одной процедурой (SPEC 18.1, NFR-ENV-01).
#   sudo deploy/envs/deploy.sh test|stage [ВЕРСИЯ] [--build]
# Запуск из рабочей копии репозитория на сервере стенда. Шаги:
#   1. проверка сервера: Docker 24+, Compose 2.24+, ОС (Ubuntu 22.04+, Astra Linux, РЕД ОС);
#   2. .env стенда: пароли — случайные (make_env.py), параметры — из deploy/envs/<стенд>/stand.env;
#   3. мастер-ключ — Docker secret в STAND_SECRETS_DIR, из .env он убирается;
#   4. список сетей Nginx из STAND_NETWORKS (офис, VPN), остальным — 403;
#   5. образы: ВЕРСИЯ из реестра (docker compose pull) или --build из рабочей копии;
#   6. миграции и запуск с ожиданием healthcheck; 7. демо-данные (STAND_SEED=demo); 8. смоук.
# Повторный запуск безопасен: пароли, ключ и данные сохраняются, обновляются образы и настройки.
# Обновление версии на работающем стенде — deploy/scripts/upgrade.sh (с резервной копией).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

usage() { sed -n '2,13p' "$0"; exit 2; }
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ОШИБКА: $*" >&2; exit 1; }

stand="${1:-}"
[[ "$stand" == test || "$stand" == stage ]] || usage
shift
version="" build=0
for arg in "$@"; do
  case "$arg" in
    --build) build=1 ;;
    -*) usage ;;
    *) version="$arg" ;;
  esac
done
STAND_DIR="$ROOT/deploy/envs/$stand"
ENV_FILE="$ROOT/.env"
SECRETS="${STAND_SECRETS_DIR:-/etc/estimator/secrets}"
APP_UID=10001  # пользователь приложения в образе api (deploy/docker/api.Dockerfile)

# --- 1. сервер ---------------------------------------------------------------------------------
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]; }

check_server() {
  command -v docker >/dev/null || die "нет docker (нужен Docker 24+)"
  local engine compose
  engine="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" \
    || die "Docker не отвечает: запущен ли сервис docker и есть ли права у пользователя"
  version_ge "$engine" 24.0 || die "Docker $engine, нужен 24+"
  compose="$(docker compose version --short 2>/dev/null)" || die "нет docker compose v2"
  version_ge "${compose#v}" 2.24 || die "Docker Compose $compose, нужен 2.24+"
  command -v python3 >/dev/null || die "нет python3 (нужен для make_env.py)"
  local id="" ver=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    id="$(. /etc/os-release && echo "${ID-}")"
    # shellcheck disable=SC1091
    ver="$(. /etc/os-release && echo "${VERSION_ID-}")"
  fi
  case "$id" in
    ubuntu) version_ge "$ver" 22.04 || log "ВНИМАНИЕ: Ubuntu $ver, проверены 22.04+" ;;
    astra|redos) ;;
    *) log "ВНИМАНИЕ: ОС «${id:-?} $ver» не из списка NFR-COMP-03 (Ubuntu 22.04+, Astra Linux, РЕД ОС)" ;;
  esac
  log "сервер: ${id:-?} $ver, Docker $engine, Compose $compose"
}

# --- 2. .env стенда ----------------------------------------------------------------------------
set_env() { # set_env ИМЯ ЗНАЧЕНИЕ — заменить или дописать строку в .env
  local name="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v n="$name" -v v="$value" -F= '
    $1 == n { if (!done) print n "=" v; done = 1; next } { print }
    END { if (!done) print n "=" v }' "$ENV_FILE" >"$tmp"
  cat "$tmp" >"$ENV_FILE"
  rm -f "$tmp"
}

env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

prepare_env() {
  python3 deploy/compose/make_env.py
  chmod 600 "$ENV_FILE"
  local line name
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    name="${line%%=*}"
    set_env "$name" "${line#*=}"
  done <"$STAND_DIR/stand.env"
  [[ -n "$version" ]] && set_env APP_VERSION "$version"
  log ".env стенда $stand готов (APP_ENV=$(env_value APP_ENV), версия $(env_value APP_VERSION))"
}

# --- 3. мастер-ключ — Docker secret ------------------------------------------------------------
prepare_secrets() {
  local key file="$SECRETS/encryption_key" mark="# docker-secret: ENCRYPTION_KEY"
  install -d -m 0700 "$SECRETS"
  key="$(env_value ENCRYPTION_KEY)"
  if [[ ! -s "$file" ]]; then
    [[ -n "$key" ]] || die "ENCRYPTION_KEY нет ни в $file, ни в .env"
    (umask 077; printf '%s' "$key" >"$file")
    log "мастер-ключ перенесён в Docker secret $file"
  elif [[ -n "$key" && "$key" != "$(cat "$file")" ]]; then
    die "ENCRYPTION_KEY в .env отличается от $file: удалите строку из .env, ключ в файле — действующий"
  fi
  chown "$APP_UID:$APP_UID" "$file"
  chmod 0400 "$file"
  # Ключ в окружении перекрыл бы secret: убираем строку и ставим пометку для make_env.py
  sed -i '/^ENCRYPTION_KEY=/d' "$ENV_FILE"
  grep -qxF "$mark" "$ENV_FILE" || printf '%s\n' "$mark" >>"$ENV_FILE"
  set_env STAND_SECRETS_DIR "$SECRETS"
}

# --- 4. сети стенда ----------------------------------------------------------------------------
prepare_access() {
  local file="$STAND_DIR/access.conf" net
  local -a nets
  read -r -a nets <<<"$(env_value STAND_NETWORKS)"
  ((${#nets[@]})) || die "STAND_NETWORKS пуст: укажите офисную сеть и VPN в $STAND_DIR/stand.env"
  {
    echo "# Создан deploy/envs/deploy.sh $stand из STAND_NETWORKS; правьте stand.env, не этот файл"
    # Своя сеть Docker стенда: запросы с самого сервера (смоук, проверки) приходят из неё
    echo "allow 127.0.0.1;"
    echo "allow $(env_value STAND_DOCKER_SUBNET);"
    for net in "${nets[@]}"; do
      [[ "$net" =~ ^[0-9a-fA-F.:]+(/[0-9]{1,3})?$ ]] || die "STAND_NETWORKS: «$net» не адрес или CIDR"
      echo "allow $net;"
    done
    echo "deny all;"
  } >"$file"
  chmod 644 "$file"
  set_env STAND_ACCESS_FILE "$file"
  log "Nginx пускает только: ${nets[*]}"
}

# --- 5–8. образы, запуск, данные, проверка -----------------------------------------------------
compose() {
  local -a cmd=(docker compose --env-file "$ENV_FILE")
  local f
  for f in $(env_value COMPOSE_FILES); do cmd+=(-f "$ROOT/$f"); done
  COMPOSE_PROFILES="$(env_value COMPOSE_PROFILES)" "${cmd[@]}" "$@"
}

start() {
  mkdir -p deploy/compose/certs
  if ((build)); then compose build; else compose pull --ignore-buildable; fi
  log "миграции и запуск (ожидание healthcheck)"
  compose up -d --wait --remove-orphans
}

seed() {
  case "$(env_value STAND_SEED)" in
    demo)
      log "демо-данные (seed-demo; уже созданные пропускаются)"
      compose run --rm --no-deps -T api estimator seed-demo ;;
    none|"") ;;
    *) die "STAND_SEED: demo или none" ;;
  esac
}

smoke() {
  local url host port ca="$ROOT/deploy/compose/certs/ca.crt" body
  local -a tls=()
  url="$(env_value APP_BASE_URL)"
  host="${url#https://}" host="${host%%/*}"
  port="$(env_value HTTPS_PORT)"
  # Сертификат стенда: dev-УЦ сервиса certs (test) или корпоративный УЦ из хранилища ОС (stage)
  [[ -s "$ca" ]] && tls=(--cacert "$ca")
  compose exec -T api python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status != 200)" \
    || die "/health/ready не зелёный"
  body="$(curl -sS --fail "${tls[@]}" --resolve "$host:${port:-443}:127.0.0.1" "https://$host:${port:-443}/")" \
    || die "https://$host/ не отвечает с сервера (сертификат, Nginx или список сетей)"
  [[ "$body" == *'<div id="root">'* ]] || die "https://$host/ отдаёт не приложение"
  log "смоук: /health/ready зелёный, https://$host/ отдаёт приложение"
}

check_server
prepare_env
prepare_secrets
prepare_access
start
seed
smoke
log "стенд $stand развёрнут: $(env_value APP_BASE_URL)"
