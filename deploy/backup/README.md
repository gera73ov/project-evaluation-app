# Резервное копирование и восстановление (INF-012)

SPEC 18.2, NFR-REL-02 (RPO ≤ 15 минут, RTO ≤ 4 часа), NFR-REL-06 (копии 30 дней),
SEC-CRYPT-04, SEC-CRYPT-07, FR-SA-07 (файл-метка). Полная инструкция службы эксплуатации —
`manuals/operations.md`.

## Как устроено

| Что | Как | Где |
|---|---|---|
| БД, непрерывно | `archive_command` → `pgbackrest archive-push`, `archive_timeout = 60 с` | том `backups` |
| БД, ежедневно | `backup.sh`: полная копия pgBackRest, `expire` старше 30 дней | том `backups` |
| Документы заказчика | `backup.sh`: архив тома `documents` (файлы уже зашифрованы AES-256-GCM, SEC-CRYPT-06) | `backups/documents/` |
| Файл-метка | `backup.sh` пишет время успеха в том `backupmark` → `BACKUP_MARKER_PATH` у api | «Состояние системы» |
| Выгрузки | не копируются: живут 24 часа (FR-EXP-05) | — |

Образ БД — `deploy/docker/postgres.Dockerfile` (PostgreSQL 16 + pgBackRest из подписанного
репозитория Alpine), настройки — `pgbackrest.conf`. Репозиторий копий шифруется AES-256 паролем
`BACKUP_CIPHER_PASSWORD`; пароль хранится **отдельно от копий** — на stage и prod это Docker secret,
запечатанная копия — в сейфе ИБ вместе с мастер-ключом `ENCRYPTION_KEY` (без мастер-ключа секреты
настроек и документы из копии не расшифровать).

На stage и prod том `backups` переопределяется на отдельный диск или сетевое хранилище службы
эксплуатации (не тот диск, где `pgdata`), например в своём compose-файле стенда:

```yaml
volumes:
  backups:
    driver: local
    driver_opts: { type: none, o: bind, device: /mnt/backup/estimator }
```

## Команды

| Команда | Что делает |
|---|---|
| `deploy/backup/backup.sh` | полная копия БД и тома документов, чистка старше 30 дней, файл-метка |
| `deploy/backup/backup.sh --check` | проверить, что архивация WAL работает (`pgbackrest check`) |
| `deploy/backup/restore.sh [--time "…"] [--wipe]` | восстановить на последнюю точку или на момент времени |
| `deploy/backup/verify-restore.sh [протокол.md]` | **только test**: копия → потеря тома БД → восстановление → проверка RPO и RTO (QA-025) |

Расписание — `estimator-backup.cron` (полная копия в 01:00, проверка архивации ежечасно).
Скрипты работают с compose-файлами из `COMPOSE_FILES` (по умолчанию —
`deploy/compose/docker-compose.yml`) и `.env` из `ENV_FILE`; профили — через `COMPOSE_PROFILES`.

## Восстановление коротко

1. Достать из сейфа ИБ пароль репозитория и мастер-ключ (акт вскрытия), положить их в secrets стенда.
2. `deploy/backup/restore.sh` (диск БД цел) или `deploy/backup/restore.sh --wipe` (диск потерян);
   на момент времени — `--time "2026-11-11 09:30:00+03"`.
3. Скрипт останавливает приложение, восстанавливает БД и документы, поднимает стенд и ждёт
   healthcheck. Затем проверить «Состояние системы» и `estimator audit verify`.

Проект, удалённый `estimator project purge`, уходит из копий по истечении их срока (30 дней,
BR-PRJ-04).
