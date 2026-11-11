#!/usr/bin/env bash
# INF-018 · установка домашнего стенда одной командой (Linux Mint 21/22, Ubuntu 22.04/24.04).
# Делает шаги 1–4 из deploy/home-stand/README.md: обновления, ufw, запрет сна, Docker Engine,
# пользователь stand (без пароля и sudo, в группе docker), исполнитель GitHub Actions с меткой
# home-stand как служба. Повторный запуск безопасен: готовые шаги пропускаются.
#
# Запуск из СВОЕЙ учётки (не из stand):
#   sudo bash setup.sh <ТОКЕН>
# Токен: GitHub → Settings → Actions → Runners → New self-hosted runner → строка
# `./config.sh --url … --token XXXXX` (действует около часа).
set -euo pipefail

REPO_URL="https://github.com/gera73ov/project-evaluation-app"
RUNNER_USER="stand"
RUNNER_NAME="home-mint"
RUNNER_LABELS="home-stand"
RUNNER_DIR="/home/${RUNNER_USER}/actions-runner"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запустите через sudo: sudo bash $0 <ТОКЕН>"
[[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "${RUNNER_USER}" ]] \
  || die "запускайте из своей учётки, а не из ${RUNNER_USER} и не из чистого root"
TOKEN="${1:-}"
[[ -n "$TOKEN" ]] || die "не передан токен исполнителя (см. начало файла)"
[[ "$(uname -m)" == "x86_64" ]] || die "нужен компьютер x86-64, а здесь $(uname -m)"
. /etc/os-release
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
[[ -n "$CODENAME" ]] || die "не удалось определить версию Ubuntu, на которой основана система"

step "1/6 Обновления и пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y full-upgrade
apt-get install -y ca-certificates curl git make python3 jq unattended-upgrades ufw

step "2/6 Брандмауэр и запрет сна"
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null

step "3/6 Docker Engine (репозиторий Docker для Ubuntu ${CODENAME})"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker run --rm hello-world >/dev/null && echo "Docker работает"

step "4/6 Пользователь ${RUNNER_USER}"
if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$RUNNER_USER"   # без пароля: входить через sudo -iu stand
fi
usermod -aG docker "$RUNNER_USER"
id "$RUNNER_USER"

step "5/6 Исполнитель GitHub Actions"
if [[ -f "${RUNNER_DIR}/.runner" ]]; then
  echo "Исполнитель уже настроен в ${RUNNER_DIR} — пропускаю (удалить: ./config.sh remove)"
else
  REL="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
  VER="$(jq -r .tag_name <<<"$REL" | sed 's/^v//')"
  SHA="$(jq -r .body <<<"$REL" | sed -n 's/.*BEGIN SHA linux-x64 -->\([0-9a-f]\{64\}\)<!-- END SHA linux-x64.*/\1/p' | head -1)"
  [[ -n "$VER" && -n "$SHA" ]] || die "не удалось узнать версию и контрольную сумму исполнителя"
  TGZ="actions-runner-linux-x64-${VER}.tar.gz"
  sudo -u "$RUNNER_USER" mkdir -p "$RUNNER_DIR"
  cd "$RUNNER_DIR"
  sudo -u "$RUNNER_USER" curl -fsSL -o "$TGZ" \
    "https://github.com/actions/runner/releases/download/v${VER}/${TGZ}"
  echo "${SHA}  ${TGZ}" | sha256sum -c -
  sudo -u "$RUNNER_USER" tar xzf "$TGZ"
  rm -f "$TGZ"
  ./bin/installdependencies.sh
  sudo -u "$RUNNER_USER" ./config.sh --unattended --url "$REPO_URL" --token "$TOKEN" \
    --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work --replace
fi

step "6/6 Служба исполнителя"
cd "$RUNNER_DIR"
[[ -f .service ]] || ./svc.sh install "$RUNNER_USER"   # svc.sh install создаёт файл .service
./svc.sh start
systemctl is-active "$(cat .service)" || die "служба не запустилась: sudo ./svc.sh status в ${RUNNER_DIR}"

printf '\n\033[1;32mГотово.\033[0m Проверьте: GitHub → Settings → Actions → Runners → %s (Idle).\n' "$RUNNER_NAME"
