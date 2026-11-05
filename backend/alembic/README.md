# Миграции БД (Alembic)

Трек DB (PLAN.md раздел 5). Контракт схемы — [`contracts/db/schema.md`](../../contracts/db/schema.md):
расхождение миграции и контракта — дефект миграции (AGENTS.md К-05). Миграции создаёт только трек DB,
история линейная; доменному треку нужна колонка — CR в PLAN.md раздел 14 и задача DB.

## Запуск

```bash
# из backend/, адрес — DATABASE_URL (как у приложения)
uv run estimator migrate              # = alembic upgrade head
uv run alembic downgrade base         # откат всего (проверяется тестами)
uv run alembic check                  # модели ORM совпадают со схемой после миграций
```

В compose миграции выполняет одноразовый сервис `migrate` до старта `api`, `worker` и `beat`.
Тесты с БД (`TEST_DATABASE_URL`) накатывают `upgrade head` на свою базу (tests/plugins/database.py).

## Роли БД (contracts/db/schema.md G-14)

| Роль | Что может | Кто от неё работает |
|---|---|---|
| `estimator_migrator` | Владелец всех объектов в `public` и схемы `audit` | `estimator migrate` (Alembic, `SET ROLE` в env.py) |
| `estimator_app` | DML в `public` (права по умолчанию); в `audit` — `SELECT` и функция `audit.append`; без DDL; на таблицах «только INSERT» нет `UPDATE`/`DELETE`/`TRUNCATE` | API и Celery: стартовый параметр соединения `role` (estimator/db/session.py) |
| `estimator_audit_purge` | `SELECT`, `DELETE` в `audit.audit_log`; запись `audit.audit_anchor` | `estimator audit purge` (SEC-004) |

Роли кластерные и создаются ревизией `0001_base` как `NOLOGIN`; `downgrade` их не удаляет.
Пользователь из `DATABASE_URL` должен уметь переключаться на них (`SET ROLE`):

* **dev, CI** — суперпользователь контейнера `postgres` (`POSTGRES_USER`), ничего настраивать не нужно;
* **stage, prod** — служба эксплуатации заводит учётную запись `LOGIN` без прав суперпользователя,
  владеющую базой, и выдаёт ей членство: `GRANT estimator_migrator, estimator_app,
  estimator_audit_purge TO <login>`. Создание ролей при первом запуске требует `CREATEROLE`; если его
  нет, роли заранее создаёт администратор СУБД теми же именами (миграция их не пересоздаёт).

## Правила написания

1. Файл `NNNN_<кратко>.py`, ревизия = имя файла (`0004_dictionaries`), `down_revision` — предыдущая.
   Нумерация сквозная, без пропусков (тест `tests/unit/db/test_migrations_static.py`).
2. `downgrade` обязателен и проверяется на чистой БД (`upgrade → downgrade base → upgrade`).
3. DDL пишется SQL-константами модуля и выполняется функцией `run()` миграции
   (`exec_driver_sql`: двоеточия в PL/pgSQL не принимаются за параметры). Значения в DDL не
   подставляются; данные в миграциях данных — через `sa.table()`/`op.bulk_insert` (SEC-WEB-05).
4. Имена ограничений и индексов — по соглашению `estimator.db.base.NAMING_CONVENTION`
   (`<таблица>_<столбцы>_idx`, `_key`, `_fkey`, `_<имя>_check`, `_pkey`) или явные имена из контракта.
   После миграции добавьте модель в `estimator.db.models` — `alembic check` должен молчать.
5. Перечисления — `CREATE TYPE … AS ENUM` (G-7); новое значение — `ALTER TYPE … ADD VALUE`
   отдельной ревизией; удаление значения — только через CR и шаг contract.
6. Таблица «только INSERT» (G-5): в той же ревизии `REVOKE UPDATE, DELETE, TRUNCATE ON <таблица>
   FROM estimator_app` — права по умолчанию выдают их всем таблицам `public`.

## Expand → migrate → contract (NFR-MNT-02)

Схема меняется без остановки: старая и новая версии приложения работают с одной БД.

1. **Expand** — только добавления: новая таблица, столбец `NULL` или с `DEFAULT`, новый индекс
   (`CREATE INDEX CONCURRENTLY` в отдельной ревизии с `autocommit_block`), новое значение ENUM.
   Старый код продолжает работать.
2. **Migrate** — релиз кода, который пишет в новую структуру и читает обе; перенос данных —
   миграцией данных или фоновой задачей пачками.
3. **Contract** — в следующем релизе, когда старого кода нет: `NOT NULL`, удаление столбцов,
   таблиц и значений. Ломающее изменение схемы — коммит с `!` и `BREAKING CHANGE:` (AGENTS.md 5.3.2).

В заголовке ревизии указывается задача PLAN.md и шаг (`Шаг: expand`).

## Журнал аудита (DB-009)

`audit.audit_log` секционирована по месяцам (`PARTITION BY RANGE (ts)`). Партиции на текущий
месяц и 3 вперёд создаёт `audit.ensure_partitions(n)`: миграция при установке и Celery-задача
`estimator.db.ensure_audit_partitions` ежедневно в 02:30. Если задача не отработала, записи попадают
в `audit_log_default` и не теряются. Запись — только `audit.append(…)`; хэш-цепочка — запись
журнала `agents/journal/DEC-20261105-db-audit-hash-chain.md`.
