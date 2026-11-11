# INF-004/INF-005 · команды разработчика. Нужны: Docker 24+ с compose, uv, Node.js 22, Python 3.
# Windows: запускать из WSL2 или Git Bash.
SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f deploy/compose/docker-compose.yml
COMPOSE_TEST := $(COMPOSE) -f deploy/compose/docker-compose.test.yml --profile test
export CERTS_UID := $(shell id -u)
export CERTS_GID := $(shell id -g)
UV := uv --directory backend
SEMGREP := uv run --project backend/tools/semgrep --frozen semgrep

.PHONY: help env certs build up up-test smoke smoke-test down ps logs \
        lint test test-backend test-frontend test-ad security check traceability

help: ## список команд
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

env: ## создать .env из .env.example со случайными паролями (если .env ещё нет)
	@python3 deploy/compose/make_env.py

certs: env ## выпустить dev-сертификаты в deploy/compose/certs (ca.crt — в доверенные)
	@mkdir -p deploy/compose/certs
	$(COMPOSE) run --rm certs

build: env ## собрать образы api и nginx
	$(COMPOSE) build

up: env ## поднять dev-стенд и дождаться healthcheck (https://localhost:8443)
	@mkdir -p deploy/compose/certs
	$(COMPOSE) up -d --build --wait

up-test: env ## dev-стенд + Samba AD, Mailpit, syslog TLS
	@mkdir -p deploy/compose/certs
	$(COMPOSE_TEST) up -d --build --wait

down: ## остановить стенд (данные в томах сохраняются)
	$(COMPOSE_TEST) down

SMOKE := docker run --rm --network estimator_backend --env-file .env \
	  -v $(CURDIR)/deploy/compose/certs:/certs:ro \
	  -v $(CURDIR)/deploy/compose/smoke_test.py:/opt/smoke_test.py:ro \
	  estimator-api:$${APP_VERSION:-dev} python /opt/smoke_test.py

smoke: ## смоук-проверка поднятого стенда (make up)
	$(SMOKE)

smoke-test: ## смоук-проверка стенда с эмуляторами (make up-test)
	$(SMOKE) --test-profile

ps: ## состояние контейнеров
	$(COMPOSE_TEST) ps

logs: ## логи всех сервисов
	$(COMPOSE_TEST) logs -f --tail=100

lint: ## ruff и eslint
	$(UV) run --frozen ruff check . ../deploy ../tools
	$(UV) run --frozen ruff format --check . ../deploy ../tools
	cd frontend && npm run -s lint && npm run -s typecheck

test-backend: ## pytest с порогами покрытия NFR-MNT-01
	$(UV) run --frozen pytest -n auto --cov --cov-report=term --cov-report=json:coverage.json
	$(UV) run --frozen python scripts/check_coverage.py coverage.json

test-frontend: ## vitest и сборка без inline-скриптов
	cd frontend && npm test && npm run -s build

test: test-backend test-frontend ## все юнит-тесты

# QA-012 · наборы AD на настоящем Samba AD DC: tests/integration/ad и сценарии tests/acceptance
# (G-04, G-05, G-10, G-26 — с тегом @samba). Нужен поднятый `make up-test`. Тесты идут в контейнере
# из стадии test образа api в сети стенда: своя база estimator_test_* на postgres стенда, Redis —
# база 15, Samba — dc1.test.estimator.local с dev-УЦ. Учётки тестов — qa-ad-…, удаляются после.
TEST_AD_IMAGE := estimator-api-test:dev
test-ad: env ## наборы AD на Samba (QA-012; сначала make up-test)
	docker build -f deploy/docker/api.Dockerfile --target test -t $(TEST_AD_IMAGE) .
	set -a && . ./.env && set +a && docker run --rm --network estimator_backend \
	  -v $(CURDIR)/deploy/compose/certs/ca.crt:/certs/ca.crt:ro \
	  -e TEST_DATABASE_URL="postgresql+asyncpg://estimator:$${POSTGRES_PASSWORD}@postgres:5432/postgres" \
	  -e TEST_REDIS_URL="redis://:$${REDIS_PASSWORD}@redis:6379/15" \
	  -e TEST_SAMBA_HOST=dc1.test.estimator.local -e TEST_SAMBA_CA_FILE=/certs/ca.crt \
	  -e TEST_SAMBA_ADMIN_PASSWORD="$${SAMBA_ADMIN_PASSWORD}" \
	  -e TEST_SAMBA_SERVICE_PASSWORD="$${SAMBA_TEST_PASSWORD}" \
	  $(TEST_AD_IMAGE) pytest -p no:cacheprovider -rs tests/integration/ad tests/acceptance

traceability: ## отчёт «требование → тест» по маркерам tc/spec/gherkin в build/traceability.md
	python3 tools/traceability.py

security: ## bandit, semgrep, pip-audit, npm audit, gitleaks (если установлен)
	$(UV) run --frozen --group security bandit -q -c pyproject.toml -r src ../deploy \
	  -x ../deploy/syslog/test_receiver.py
	$(SEMGREP) --test backend/semgrep/
	$(SEMGREP) scan --error --metrics=off --disable-version-check --config backend/semgrep/ \
	  --exclude "backend/semgrep/*.py" backend/src deploy
	$(UV) export -q --frozen --all-groups --no-emit-project --format requirements-txt \
	  -o .audit-requirements.txt
	$(UV) run --frozen --group security pip-audit --strict --require-hashes --disable-pip \
	  -r .audit-requirements.txt
	cd frontend && npm audit --omit=dev --audit-level=high
	@if command -v gitleaks >/dev/null; then gitleaks git --redact --no-banner .; \
	  else echo "gitleaks не установлен — проверка секретов пройдёт в CI"; fi

check: lint test security ## всё, что проверяет CI на каждый PR
