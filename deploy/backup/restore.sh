#!/usr/bin/env bash
# INF-012 · восстановление из резервной копии (SPEC 18.2, 18.3; NFR-REL-02: RPO ≤ 15 мин, RTO ≤ 4 ч).
#   deploy/backup/restore.sh                         — на последнюю точку архива WAL
#   deploy/backup/restore.sh --time "2026-11-11 09:30:00+03"  — на момент времени (PITR)
#   deploy/backup/restore.sh --wipe ...              — каталог БД пуст или потерян (новый диск)
# Порядок: остановить приложение → восстановить БД (pgbackrest restore) → документы из архива
# тома на ту же дату → поднять стенд и дождаться /health/ready. Нужен тот же пароль репозитория
# (BACKUP_CIPHER_PASS), что при копировании, и тот же мастер-ключ ENCRYPTION_KEY: без него
# секреты и документы не расшифровать (SEC-CRYPT-07, ключ — из сейфа ИБ по акту вскрытия).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

target="" wipe=0
while (($#)); do
  case "$1" in
    --time) target="$2"; shift 2 ;;
    --wipe) wipe=1; shift ;;
    *) sed -n '2,10p' "$0"; exit 2 ;;
  esac
done

started=$(date +%s)
log "останавливаю приложение и БД"
"${COMPOSE[@]}" stop nginx api worker beat postgres

if ((wipe)); then
  log "каталог БД пуст: том pgdata создаётся заново"
  "${COMPOSE[@]}" rm -f postgres >/dev/null
  docker volume rm "${PROJECT}_pgdata" >/dev/null 2>&1 || true
fi

opts=(--delta)
if [[ -n "$target" ]]; then
  opts+=(--type=time "--target=$target" --target-action=promote)
fi
log "восстанавливаю БД ${target:+на $target}"
# Свой контейнер из образа postgres: без entrypoint базового образа (иначе пустой каталог он
# инициализировал бы заново). Каталог БД — тот же том pgdata.
"${COMPOSE[@]}" run --rm --no-deps -T -u postgres --entrypoint sh postgres -ec \
  "mkdir -p /var/lib/postgresql/data && chmod 0700 /var/lib/postgresql/data \
   && pgbackrest --stanza=$STANZA ${opts[*]} restore"

# Архив тома документов: последний не позже точки восстановления (или просто последний).
log "восстанавливаю документы"
"${COMPOSE[@]}" run --rm --no-deps -T -u 0 --entrypoint sh \
  -v "${PROJECT}_documents:/restore/documents" postgres -ec "
    want='$(if [[ -n "$target" ]]; then date -u -d "$target" +%Y%m%dT%H%M%SZ; fi)'
    pick=''
    for f in \$(ls /var/lib/pgbackrest/documents/documents-*.tar 2>/dev/null | sort); do
      stamp=\${f##*/documents-}; stamp=\${stamp%.tar}
      if [ -z \"\$want\" ] || [ \"\$stamp\" \\< \"\$want\" ] || [ \"\$stamp\" = \"\$want\" ]; then pick=\$f; fi
    done
    if [ -z \"\$pick\" ]; then echo 'архива документов нет — пропускаю'; exit 0; fi
    echo \"архив \$pick\"
    find /restore/documents -mindepth 1 -delete
    tar -C /restore -xf \"\$pick\"
    chown -R 10001:10001 /restore/documents
  "

log "поднимаю стенд"
"${COMPOSE[@]}" up -d --wait
log "восстановление заняло $(( $(date +%s) - started )) с"
