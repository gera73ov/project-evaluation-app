# syntax=docker/dockerfile:1
# INF-006 · образ бэкенда: api, worker и beat (SPEC 13.2; SEC-SDLC-04, SEC-CRYPT-01).
# Контекст сборки — корень репозитория: docker build -f deploy/docker/api.Dockerfile .
# Базовый образ закреплён по дайджесту (AGENTS.md 6.5); обновление — плановым PR.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY deploy/docker/uv-requirements.txt /tmp/uv-requirements.txt
RUN pip install --require-hashes --no-deps -r /tmp/uv-requirements.txt
WORKDIR /src
# Сначала только зависимости — слой кэшируется, пока не меняется uv.lock
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
# Каталог прав (SEC-005) — из contracts/, единственного источника; кладётся в пакет
COPY contracts/permissions.yaml ./src/estimator/security/authz/permissions.yaml
RUN uv sync --frozen --no-dev --no-editable \
 && /opt/venv/bin/python -c "from estimator.security.authz.catalog import load_catalog; load_catalog()"

FROM ${PYTHON_IMAGE} AS runtime
ARG APP_VERSION=0.1.0
LABEL org.opencontainers.image.title="estimator-api" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/gera73ov/project-evaluation-app"
# Обновления безопасности ОС базового образа; pip/setuptools в рантайме не нужны
RUN apt-get update -o APT::Update::Error-Mode=any \
 && apt-get -y upgrade --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && pip uninstall -y pip setuptools wheel 2>/dev/null || true
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent \
    --shell /usr/sbin/nologin app
COPY --from=build --chown=root:root /opt/venv /opt/venv
WORKDIR /app
# Миграции Alembic для `estimator migrate` (DB-002): /app/alembic.ini → /app/alembic
COPY --chown=root:root backend/alembic.ini ./
COPY --chown=root:root backend/alembic ./alembic
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}
# Не root (SEC-SDLC-04). Файловая система только для чтения задаётся при запуске (compose).
USER 10001:10001
EXPOSE 8000
# Порт 8000 доступен только во внутренней сети compose; наружу публикует Nginx.
# FORWARDED_ALLOW_IPS (адреса Nginx) Uvicorn читает из окружения.
CMD ["uvicorn", "--factory", "estimator.main:app_factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header", "--no-date-header"]
