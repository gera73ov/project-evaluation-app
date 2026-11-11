# Приложение оценки проектов

Веб-приложение для оценки трудоёмкости и стоимости проектов внедрения: модератор собирает
команду экспертов по дисциплинам, эксперты декомпозируют работы в дереве и ставят оценки
по трём точкам (O–R–P), приложение считает E, σ, P80/P90, деньги по ставкам и «Цифру для КП».
Работа идёт совместно в реальном времени, с обсуждениями у строк, вопросами заказчику,
снимками, статистикой и выгрузками в Excel и Word. Работает во внутренней сети компании,
вход через Active Directory или по паролю приложения с TOTP.

## Документы

- [docs/spec/SPEC.md](docs/spec/SPEC.md) — спецификация, источник правды (версия 0.5 от 04.11.2026).
  Картинки макетов — `docs/spec/img/`, их HTML-исходники — `docs/spec/mockups-src/`, ревью и прошлые
  версии — `docs/spec/review/`. HTML-версия: `pip install markdown && python3 docs/spec/build.py
  docs/spec/SPEC.md spec.html docs/spec/tpl.html`.
- [PLAN.md](PLAN.md) — план реализации: этапы, треки, задачи, владение файлами.
- [DESIGN.md](DESIGN.md) — правила дизайна интерфейса.
- [AGENTS.md](AGENTS.md) — обязательный регламент работы агентов и субагентов. Журнал решений
  и инцидентов — [agents/journal/](agents/journal/).
- [manuals/](manuals/) — руководства: [пользователя](manuals/user.md),
  [администратора](manuals/admin.md), [суперадминистратора](manuals/superadmin.md),
  [инструкция службы эксплуатации ИТ](manuals/operations.md) и
  [регламенты сопровождения](manuals/regulations.md).
- [contracts/](contracts/README.md) — контракты между треками: OpenAPI, права, ошибки, события
  WebSocket, аудит, уведомления, выгрузки, настройки, эталонные фикстуры расчёта.

## Что нужно установить

Docker 24+ с compose, [uv](https://docs.astral.sh/uv/), Node.js 22 и Python 3. В Windows команды
запускаются из WSL2.

## Как поднять dev-стенд

```bash
make env       # создать .env из .env.example со случайными паролями
make up        # nginx, api ×2, worker, beat, PostgreSQL 16, Redis 7, ClamAV; ждёт healthcheck
```

Приложение открывается на https://localhost:8443. Сертификаты выпускает свой dev-УЦ, его файл
`deploy/compose/certs/ca.crt` нужно добавить в доверенные браузера.

- `make up-test` — то же плюс эмуляторы корпоративных сервисов: Samba AD DC (LDAPS на 127.0.0.1:1636),
  Mailpit (письма на http://127.0.0.1:8025), syslog-приёмник TLS вместо SIEM (127.0.0.1:6514).
  `make smoke-test` проверяет их по протоколам, `make test-ad` — наборы входа через AD на этом Samba
  (QA-012; тесты идут в контейнере в сети стенда, учётки `qa-ad-…` удаляются после себя).
- `make help` — список всех команд, `make ps` и `make logs` — состояние и логи, `make down` — остановить
  стенд (данные в томах сохраняются).

### Фронтенд без бэкенда

```bash
cd frontend && npm ci && npm run dev:mock
```

Приложение поднимается на http://localhost:5173 на моках API (MSW) с данными «Портала дилеров»
и «Интеграции с ФНС». Роль меняется переключателем в правом нижнем углу, события WebSocket
имитируются по контракту `contracts/ws-events.schema.json`. Подробнее —
[frontend/src/shared/api/mocks/README.md](frontend/src/shared/api/mocks/README.md).

`npm run dev` работает с API dev-стенда (`make up`) через прокси Vite.

## Как запускать тесты

```bash
make check          # всё, что проверяет CI на каждый PR: линтеры, тесты, сканеры
make test           # только тесты бэкенда и фронтенда
make traceability   # отчёт «требование → тест» в build/traceability.md
```

- Бэкенд: `uv --directory backend run pytest -n auto`. Пороги покрытия (NFR-MNT-01) проверяет
  `make test-backend`. Тесты с внешними сервисами помечены `integration` и требуют `make up-test`.
- Приёмочные сценарии SPEC 17.2 (G-01…G-26) лежат в `backend/tests/acceptance/features/`;
  пока шаги не реализованы, прогон показывает их как `pending`.
- Фронтенд: `cd frontend && npm test` (Vitest), `npm run lint`, `npm run typecheck`.
- Маркеры трассировки: `@pytest.mark.tc("TC-…")`, `@pytest.mark.spec("FR-…")`,
  `@pytest.mark.gherkin("G-NN")` — по ним `tools/traceability.py` строит отчёт.

## Переменные окружения

Переменные dev-стенда с комментариями — в [.env.example](.env.example). На stage и prod секреты
передаются через Docker secrets (`/run/secrets/<имя>`), а `.env` в репозиторий не попадает.

Переменные приложения (бэкенд, `backend/src/estimator/config.py`). Таблицу генерирует
`uv --directory backend run estimator config-env --write ../README.md`, CI проверяет, что она
совпадает с конфигом.

<!-- env-table:begin (estimator config-env --write README.md) -->
| Переменная | Описание | По умолчанию |
|---|---|---|
| `APP_ENV` | Окружение: dev, test, stage, prod (SPEC 18.1) | `dev` |
| `APP_VERSION` | Версия приложения для «Состояния системы» и логов; задаётся при сборке образа | `0.1.0` |
| `LOG_LEVEL` | Уровень логов: DEBUG, INFO, WARNING, ERROR | `INFO` |
| `DATABASE_URL` | Строка подключения к PostgreSQL 16 (драйвер asyncpg); секрет — пароль внутри строки (Docker secret `database_url`) | `postgresql+asyncpg://estimator@postgres:5432/estimator` |
| `DATABASE_SSLMODE` | TLS до PostgreSQL: `disable` (dev, одна сеть Docker) или `verify-full` (stage, prod: проверка сертификата и имени сервера, DB-011) | `disable` |
| `DATABASE_SSLROOTCERT` | Файл корневого сертификата УЦ для `verify-full`; пусто — системные УЦ | `` |
| `REDIS_URL` | Redis 7: сессии, pub/sub, блокировки ячеек (Docker secret `redis_url`) | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | Брокер Celery в Redis (Docker secret `celery_broker_url`) | `redis://redis:6379/1` |
| `ENCRYPTION_KEY` | Мастер-ключ шифрования AES-256-GCM в виде `<id>:<base64url 32 байта>` (SEC-CRYPT-01/02; Docker secret `encryption_key`). Новый ключ: `estimator generate-key` | `` |
| `ENCRYPTION_KEYS_OLD` | Прежние мастер-ключи через запятую в том же формате — только на время `estimator rotate-key` (SEC-CRYPT-02, SPEC 18.4); после ротации убрать | `` |
| `APP_BASE_URL` | Адрес приложения для ссылок в письмах до первичной настройки (`https://…`, без `/` в конце). После мастера настройки действует `app.base_url` | `https://localhost` |
| `APP_TIMEZONE` | Часовой пояс приложения IANA до первичной настройки: по нему считаются ночные задачи (FR-UI-02). После мастера настройки действует `app.timezone` | `Europe/Moscow` |
| `HEALTH_TIMEOUT_SECONDS` | Таймаут одной проверки `/health/ready`, секунды | `2.0` |
| `BACKUP_MARKER_PATH` | Файл-метка последней успешной резервной копии (время ISO 8601 или время изменения файла) для «Состояния системы» (FR-SA-07); пишет скрипт бэкапа | `/var/lib/estimator/backup/last-success` |
| `APP_TLS_CERT_PATH` | Сертификат TLS приложения (PEM, тот же, что у Nginx) — для метрики срока действия и оповещения «истекает < 30 дней» (18.4); пусто — не проверять | `` |
| `EXPORTS_DIR` | Каталог файлов выгрузок (том `exports`, файлы живут 24 часа, FR-EXP-05) | `/data/exports` |
| `DOCUMENTS_DIR` | Каталог зашифрованных документов заказчика (том `documents`, SEC-CRYPT-06) | `/data/documents` |
| `CLAMAV_HOST` | Адрес `clamd` для проверки документов заказчика (SEC-WEB-10) | `clamav` |
| `CLAMAV_PORT` | TCP-порт `clamd` | `3310` |
| `CLAMAV_TIMEOUT_SECONDS` | Таймаут проверки одного документа в `clamd`, секунды | `60.0` |
| `TRUSTED_HOSTS` | Разрешённые значения заголовка Host через запятую; на stage и prod — имя сервера | `*` |
<!-- env-table:end -->

Переменные стенда и скриптов эксплуатации. Их читают `docker compose` (файлы
`deploy/compose/*.yml`) и скрипты `deploy/backup`, `deploy/scripts`, `deploy/logging`, а не
приложение. CI проверяет, что каждая переменная из этих файлов есть в таблице ниже.

<!-- ops-env-table:begin -->
| Переменная | Кто читает | Описание | По умолчанию |
|---|---|---|---|
| `APP_VERSION` | compose | Тег образов `estimator-*` и версия в «Состоянии системы»; на stage и prod — тег релиза | `dev` |
| `FORWARDED_ALLOW_IPS` | Uvicorn (`api`) | Каким адресам верить в `X-Forwarded-For`: на stage и prod — адрес контейнера Nginx, не `*` | `127.0.0.1` (Uvicorn) |
| `POSTGRES_PASSWORD` | compose | Пароль роли `estimator` в PostgreSQL; из него compose собирает `DATABASE_URL` | обязателен |
| `REDIS_PASSWORD` | compose | Пароль Redis; из него собираются `REDIS_URL` и `CELERY_BROKER_URL` | обязателен |
| `BACKUP_CIPHER_PASSWORD` | compose (`postgres`) | Пароль шифрования репозитория копий pgBackRest (AES-256); хранится отдельно от копий, копия — в сейфе ИБ | обязателен |
| `HTTPS_PORT`, `HTTP_PORT` | compose (`nginx`) | Порты Nginx на 127.0.0.1 в dev; на stage и prod порты задаёт файл стенда | `8443`, `8080` |
| `POSTGRES_PORT`, `REDIS_PORT` | compose | Порты PostgreSQL и Redis на 127.0.0.1 (только dev) | `5432`, `6379` |
| `PROMETHEUS_PORT` | compose (профиль `monitoring`) | Порт Prometheus на 127.0.0.1 | `9090` |
| `CERTS_UID`, `CERTS_GID` | compose | Владелец файлов сертификатов, которые выпускает сервис `certs` | `10001` |
| `SAMBA_ADMIN_PASSWORD`, `SAMBA_TEST_PASSWORD` | `docker-compose.test.yml` | Пароли эмулятора AD (Samba) на test | обязателен на test |
| `LDAPS_PORT`, `LDAP_PORT` | `docker-compose.test.yml` | Порты эмулятора AD на 127.0.0.1 | `1636`, `1389` |
| `MAILPIT_UI_PORT` | `docker-compose.test.yml` | Веб-интерфейс эмулятора почты | `8025` |
| `SYSLOG_TLS_PORT`, `SYSLOG_REQUIRE_CLIENT_CERT` | `docker-compose.test.yml` | Эмулятор SIEM: порт syslog over TLS и требование клиентского сертификата (mTLS) | `6514`, `0` |
| `ROOT` | `deploy/backup` | Корень рабочей копии репозитория на сервере | каталог над `deploy/` |
| `ENV_FILE` | `deploy/backup`, `deploy/scripts` | Файл переменных стенда | `.env` в корне репозитория |
| `COMPOSE_FILES` | `deploy/backup`, `deploy/scripts` | Файлы compose через двоеточие, например основной и файл стенда | `deploy/compose/docker-compose.yml` |
| `COMPOSE_PROJECT_NAME` | `deploy/backup`, `deploy/scripts` | Имя проекта compose | `estimator` |
| `BACKUP_KEEP_DAYS` | `backup.sh` | Сколько дней хранить полные копии (NFR-REL-06) | `30` |
| `WAIT_ARCHIVE` | `verify-restore.sh` | Сколько секунд ждать архивации WAL перед аварией в проверке восстановления | `75` |
| `HEALTH_TIMEOUT` | `upgrade.sh`, `rollback.sh` | Сколько секунд ждать зелёного healthcheck сервиса после перезапуска | `180` |
| `LOG_DIR` | `collect-logs.sh` | Каталог, куда собираются логи контейнеров | `/var/log/estimator` |
| `LOG_RETENTION_DAYS` | `collect-logs.sh` | Сколько дней хранить собранные логи (NFR-REL-06) | `90` |
| `API_REPLICAS` | compose (`api`) | Сколько реплик API запустить; Nginx и Prometheus находят их все через DNS сервиса. Больше двух — если нагрузочный тест (`load/README.md`) упирается в процессор | `2` |
| `BIND_ADDRESS` | compose (`nginx`) | На каком адресе сервера открыты порты HTTPS и HTTP: `127.0.0.1` на dev, `0.0.0.0` на стендах test и stage | `127.0.0.1` |
| `STAND_SECRETS_DIR` | `deploy/envs/deploy.sh`, compose стендов | Каталог Docker secrets стенда на сервере: в нём файл `encryption_key` (мастер-ключ) | `/etc/estimator/secrets` |
| `STAND_ACCESS_FILE` | compose стендов (`nginx`) | Список сетей, которым Nginx отвечает; его пишет `deploy/envs/deploy.sh` из `STAND_NETWORKS` | пишет `deploy.sh` |
| `STAND_DOCKER_SUBNET` | compose стендов | Подсеть Docker стенда; Nginx пускает её, чтобы работали проверки с самого сервера | `172.31.250.0/24` |
<!-- ops-env-table:end -->

Как задать переменные на stage и prod, где лежат секреты и как их менять — в
[инструкции службы эксплуатации](manuals/operations.md#3-установка-на-stage-и-prod).

Настройки, которые меняет суперадминистратор в интерфейсе (режим входа, SMTP, SIEM, политики),
хранятся в БД, а не в окружении; их ключи описаны в `contracts/settings.schema.json`.

## Структура репозитория

| Каталог | Что внутри |
|---|---|
| `backend/` | API (FastAPI), фоновые задачи (Celery), CLI `estimator`, тесты pytest |
| `frontend/` | SPA (React 18, Vite, TypeScript, Mantine), моки API |
| `contracts/` | Контракты между треками (фиксируются вехой M0) |
| `deploy/` | Docker Compose, образы, nginx, эмуляторы AD/SMTP/SIEM |
| `e2e/` | Сквозные тесты Playwright |
| `tools/` | Служебные скрипты репозитория (отчёт трассировки) |
| `docs/` | Спецификация, решения по пробелам, презентация |
| `manuals/` | Руководства пользователей и службы эксплуатации, регламенты |
