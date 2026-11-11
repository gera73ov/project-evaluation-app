# syntax=docker/dockerfile:1
# INF-012 · PostgreSQL 16 с pgBackRest: непрерывная архивация WAL и полные копии (SPEC 18.2,
# NFR-REL-02, SEC-CRYPT-04). Контекст сборки — корень репозитория:
#   docker build -f deploy/docker/postgres.Dockerfile .
# pgBackRest — из подписанного репозитория Alpine (apk проверяет подпись пакета).
ARG POSTGRES_IMAGE=postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab

FROM ${POSTGRES_IMAGE}
RUN apk upgrade --no-cache \
 && apk add --no-cache pgbackrest \
 && pgbackrest version \
 && install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest \
 && install -d -o postgres -g postgres -m 0755 /var/lib/estimator/backup \
 # том documents подключается и сюда (только чтение, для архива): если postgres стартует первым,
 # новый том берёт владельца этого каталога — тот же, что в образе api (uid 10001)
 && install -d -o 10001 -g 10001 -m 0750 /data/documents
COPY --chmod=0644 deploy/backup/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY --chmod=0755 deploy/backup/pgbackrest-archive.sh /usr/local/bin/pgbackrest-archive.sh
