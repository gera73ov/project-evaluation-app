# syntax=docker/dockerfile:1
# INF-012 · PostgreSQL 16 с pgBackRest: непрерывная архивация WAL и полные копии (SPEC 18.2,
# NFR-REL-02, SEC-CRYPT-04). Контекст сборки — корень репозитория:
#   docker build -f deploy/docker/postgres.Dockerfile .
# pgBackRest — из подписанного репозитория Alpine (apk проверяет подпись пакета).
ARG POSTGRES_IMAGE=postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab

FROM ${POSTGRES_IMAGE} AS build
RUN apk upgrade --no-cache \
 && apk add --no-cache pgbackrest su-exec \
 && pgbackrest version \
 # gosu базового образа собран старым Go (trivy: CRITICAL/HIGH в stdlib); su-exec из Alpine
 # принимает те же аргументы («gosu postgres …»), которыми его зовёт docker-entrypoint.sh
 && rm -f /usr/local/bin/gosu && ln -s /sbin/su-exec /usr/local/bin/gosu \
 && gosu postgres true \
 && install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest \
 && install -d -o postgres -g postgres -m 0755 /var/lib/estimator/backup \
 # том documents подключается и сюда (только чтение, для архива): если postgres стартует первым,
 # новый том берёт владельца этого каталога — тот же, что в образе api (uid 10001)
 && install -d -o 10001 -g 10001 -m 0750 /data/documents
COPY --chmod=0644 deploy/backup/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY --chmod=0755 deploy/backup/pgbackrest-archive.sh /usr/local/bin/pgbackrest-archive.sh

# Один слой: иначе старый gosu остаётся в нижнем слое образа (и в отчёте trivy). Метаданные
# базового образа (ENV, VOLUME, ENTRYPOINT…) при копировании теряются — задаём их снова.
FROM scratch
COPY --from=build / /
ENV PG_MAJOR=16 \
    LANG=en_US.utf8 \
    PGDATA=/var/lib/postgresql/data \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
VOLUME /var/lib/postgresql/data
ENTRYPOINT ["docker-entrypoint.sh"]
STOPSIGNAL SIGINT
EXPOSE 5432
CMD ["postgres"]
