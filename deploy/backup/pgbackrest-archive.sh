#!/bin/sh
# INF-012 · archive_command PostgreSQL: WAL-сегмент → репозиторий pgBackRest. В имени — «pgbackrest»:
# pgbackrest check и backup требуют, чтобы archive_command его содержал.
# Пока stanza не создана (первый запуск backup.sh), копий нет и WAL восстанавливать не к чему:
# сегмент считается обработанным, иначе он копился бы в pg_wal и заполнил диск. Отсутствие копий
# ловит оповещение «бэкап старше 26 часов».
set -eu
if [ -d /var/lib/pgbackrest/archive/estimator ]; then
  exec pgbackrest --stanza=estimator archive-push "$1"
fi
exit 0
