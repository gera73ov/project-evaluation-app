# syntax=docker/dockerfile:1
# INF-006 · образ фронтенда: сборка SPA и Nginx (SPEC 13.2; SEC-SDLC-04).
# Контекст сборки — корень репозитория: docker build -f deploy/docker/nginx.Dockerfile .
# Настройка Nginx (заголовки, CSP с nonce, лимиты) — deploy/nginx, INF-009.
ARG NODE_IMAGE=node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
# 1.30.7 закрывает CVE-2026-121810, -123007, -123633 и другие (trivy 19.11.2026), исключение из правила 14 дней
ARG NGINX_IMAGE=nginx:1.30.7-alpine@sha256:bef154735288bc38d99fac41ae63730684bcc661503673a04a0f9bc526ba8598

FROM ${NODE_IMAGE} AS build
# Раскладка как в репозитории: tsc проверяет моки (FE-001), а они импортируют ../contracts.
# В dist моки не попадают (это проверяет scripts/check-build.mjs).
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --ignore-scripts --no-audit
COPY contracts/ /src/contracts/
COPY frontend/ ./
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
RUN apk upgrade --no-cache \
 && rm -f /etc/nginx/conf.d/default.conf \
 && mkdir -p /etc/nginx/access
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/log_format.conf /etc/nginx/log_format.conf
COPY deploy/nginx/conf.d/ /etc/nginx/conf.d/
COPY deploy/nginx/snippets/ /etc/nginx/snippets/
COPY --from=build /src/frontend/dist /usr/share/nginx/html
# Не root: пользователь nginx из базового образа (uid 101), порты выше 1024,
# pid и временные файлы — в /tmp (файловая система только для чтения, кроме /tmp).
USER 101:101
EXPOSE 8080 8443
# Без docker-entrypoint.d базового образа: он правит конфиги, а файловая система только для чтения
ENTRYPOINT ["nginx", "-g", "daemon off;"]
CMD []
