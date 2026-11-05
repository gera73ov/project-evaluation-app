# syntax=docker/dockerfile:1
# INF-006 · образ фронтенда: сборка SPA и Nginx (SPEC 13.2; SEC-SDLC-04).
# Контекст сборки — корень репозитория: docker build -f deploy/docker/nginx.Dockerfile .
# Полная настройка Nginx (заголовки, CSP с nonce, лимиты) — INF-009.
ARG NODE_IMAGE=node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
ARG NGINX_IMAGE=nginx:1.30-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949

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
 && rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/conf.d/ /etc/nginx/conf.d/
COPY --from=build /src/frontend/dist /usr/share/nginx/html
# Не root: пользователь nginx из базового образа (uid 101), порты выше 1024,
# pid и временные файлы — в /tmp (файловая система только для чтения, кроме /tmp).
USER 101:101
EXPOSE 8443
# Без docker-entrypoint.d базового образа: он правит конфиги, а файловая система только для чтения
ENTRYPOINT ["nginx", "-g", "daemon off;"]
CMD []
