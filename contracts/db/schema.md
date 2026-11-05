# Контракт схемы БД (DB-001)

Версия контракта: **0.1 (черновик до вехи M0)**. Владелец: трек DB. Основание: SPEC v0.5, разделы 14.1–14.3,
ARCH-02…ARCH-04, SEC-AUTHZ-03/04, SEC-AUD-02/03, BR-CALC-03, NFR-LIM-01.
Диаграмма связей — [`erd.mmd`](erd.mmd).

Документ фиксирует **все таблицы 14.2** (43 позиции, включая `project_totals_daily` по решению GAP-01),
их столбцы, типы, перечисления, ограничения и индексы, а также решения, которые SPEC оставляет на выбор.
По нему пишут миграции задачи DB-002…DB-010; ORM-модели, сервисы и контрактные тесты опираются на имена
отсюда. Расхождение миграции и этого документа — дефект миграции (AGENTS.md К-05).

Как читать таблицы столбцов: «NN» — `NOT NULL`; «—» в столбце «По умолчанию» — значение задаёт приложение.
Ссылка «→ `table`» означает внешний ключ на `table.id` (если не указано иное).

---

## 1. Общие правила

| № | Правило | Основание |
|---|---|---|
| G-1 | СУБД — PostgreSQL 16. Расширения: `citext` (логины, email). Других расширений не требуется | 13.1, DB-002 |
| G-2 | Первичные ключи — `UUID` версии 7, генерирует приложение (`estimator.db.uuid7`), без `DEFAULT` в БД. Исключения названы в таблицах: составные ключи, `currencies.code`, `system_settings.key`, `work_calendar.date`, `sessions.id_hash` | 14.2, SEC-AUTHZ-03 |
| G-3 | Все моменты времени — `TIMESTAMPTZ`, хранятся в UTC; сессия БД работает с `timezone = 'UTC'`. Календарные даты (дедлайн, день итогов, производственный календарь) — `DATE` и считаются по часовому поясу приложения `app.timezone` | 14.2, FR-UI-02 |
| G-4 | Аудиторские поля изменяемых таблиц: `created_at TIMESTAMPTZ NN DEFAULT now()`, `created_by UUID NULL → users`, `updated_at TIMESTAMPTZ NN DEFAULT now()`, `updated_by UUID NULL → users`. `NULL` в `*_by` означает «Система» (фоновая задача, консольная команда). Таблицы, где поля есть, помечены значком **[А]** | 14.2 |
| G-5 | Таблицы «только INSERT» (`node_history`, `message_history`, `audit.audit_log`): у роли приложения `estimator_app` нет прав `UPDATE`, `DELETE`, `TRUNCATE`. Права выдаёт миграция (DB-002, DB-006, DB-007, DB-009) | SEC-AUD-03, 14.2 |
| G-6 | Логическое удаление: пользователи — `status` (физически не удаляются, только анонимизация); справочники — `is_active`; узлы и документы — `deleted_at` (корзина 30 дней, затем физическое удаление ночной задачей) | 14.2, FR-TREE-24, FR-DOC-01 |
| G-7 | Перечисления — типы PostgreSQL `ENUM` с именами из этого документа. Добавление значения — `ALTER TYPE … ADD VALUE` (расширяющая миграция); удаление значения — только через CR и contract-шаг | 14.2, NFR-MNT-02 |
| G-8 | Десятичные значения — только `NUMERIC` с указанной точностью; `REAL`/`DOUBLE PRECISION` запрещены. Часы O/R/P — `NUMERIC(10,2)`, часы итогов — `NUMERIC(14,2)`, ставки — `NUMERIC(12,0)`, курс — `NUMERIC(12,4)`, проценты — `NUMERIC(5,2)`, деньги — `NUMERIC(20,0)` | BR-CALC-03, BR-MONEY-04 |
| G-9 | Десятичные значения внутри JSONB (`node_history.changes`, `snapshots.payload`, `change_log.event`, `project_journal.changes`) пишутся **строками** (`"12.5"`), как в API (15.1), чтобы не терять точность | 15.1, BR-CALC-03 |
| G-10 | Суммы по узлам в БД не хранятся (кроме кэшей `project_totals`, `project_totals_daily` для списков) | ARCH-03 |
| G-11 | Деньги живут только в `project_money`, `project_rates`, денежных столбцах `project_totals`/`project_totals_daily` и `snapshots.money_payload`. ORM-модели денег вынесены в модуль `estimator.db.models.money`; импорт модуля разрешён только сервису денег (правило import-linter, DB-005) | SEC-AUTHZ-04 |
| G-12 | Внешние ключи на `users` не каскадные (`ON DELETE RESTRICT`): пользователи не удаляются. Внутри проекта ключи `ON DELETE CASCADE` от `projects`, чтобы работала команда `estimator project purge` (BR-PRJ-04); у `audit.audit_log` внешних ключей нет | BR-PRJ-04, SEC-AUD-03 |
| G-13 | Сырые SQL-строки с подстановкой значений запрещены (semgrep `raw-sql`); исключение — функции и DDL внутри миграций | SEC-WEB-05 |
| G-14 | Роли БД: `estimator_migrator` (владелец схем, выполняет Alembic), `estimator_app` (рабочая роль API и Celery), `estimator_audit_purge` (только `audit purge`). Схемы: `public` (данные приложения), `audit` (журнал аудита, владелец — `estimator_migrator`) | DB-002, SEC-AUD-03/04 |
| G-15 | Длины строк по NFR-LIM-01 закрепляются в БД `VARCHAR(n)` или `CHECK (char_length(…) …)`; сервер дополнительно валидирует их до записи и отвечает 422 `VALUE_OUT_OF_RANGE` / `VALIDATION_FAILED` | NFR-LIM-01, 15.3 |

### 1.1. Решения, которые SPEC оставляет на выбор

| ID | Вопрос | Решение | Основание |
|---|---|---|---|
| DB-D01 | Где хранить `app_params` (пороги детализации, % УП по умолчанию, ожидаемое число единиц «Средне», срок автоархивации) | Отдельной таблицы нет. Значения — ключи `method.*` в `system_settings` (схема ключей — `contracts/settings.schema.json`, задача ADM-000). Редактирует администратор | 14.2 `app_params` («можно хранить в `system_settings` под ключами `method.*`») |
| DB-D02 | Где хранить `totp_used_codes` | Redis: ключ `totp:used:{user_id}:{time_step}`, TTL 120 с, `SET NX`. Таблицы в PostgreSQL нет. Потеря ключей при перезапуске Redis допустима: окно повтора не больше 90 с, а сессии при этом тоже теряются (ARCH-05) | 14.2 `totp_used_codes` («может жить в Redis с TTL»), FR-2FA-01 |
| DB-D03 | Уникальность ставок и участников при `NULL` | `UNIQUE NULLS NOT DISTINCT` (PostgreSQL 15+): `project_rates (project_id, discipline_id)`, `project_members (project_id, user_id, role, discipline_id)` | 14.2 |
| DB-D04 | Формат перечислений | Типы `ENUM` PostgreSQL (правило G-7) | 14.2 |
| DB-D05 | Счётчики неудачных входов, блокировки пар «логин + IP», rate limit, активные сессии, захваты ячеек, присутствие | Redis (раздел 5), не PostgreSQL | 14.2 `users`, `sessions`, FR-TREE-31 |
| DB-D06 | Столбцы `kind` уведомлений, выгрузок и тип события аудита | `TEXT` с проверкой значения приложением по каталогам `notifications.yaml`, `exports.yaml`, `audit-events.yaml` (владельцы NTF, EXP, SEC). В БД не `ENUM`, чтобы новый вид из каталога не требовал миграции | NTF-001, EXP-001, SEC-002 |
| DB-D07 | Таблицы, которых нет в 14.2, но которые нужны требованиям SPEC | `auth_tokens` (SEC-AUTH-03), `project_journal` (11.6 №1, GAP-02), `audit.audit_anchor` (SEC-AUD-04). Описаны в разделе 3 | см. раздел 3 |
| DB-D08 | Столбцы сверх 14.2 | Перечислены в разделе 4 с основанием. Поведение продукта они не меняют: только хранят то, что требует SPEC | см. раздел 4 |

---

## 2. Таблицы 14.2

Порядок — как в 14.2. В колонке «Задача» — задача, которая создаёт таблицу миграцией (PLAN.md 13.2).

### 2.1. Пользователи, сессии, настройки (DB-003)

#### `users` [А]

| Столбец | Тип | NN | По умолчанию | Ограничения и смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| login | CITEXT | ✓ | — | `UNIQUE`; `CHECK (char_length(login) BETWEEN 3 AND 64)`. Для local — `^[A-Za-z0-9._-]{3,64}$` (FR-AUTH-LOC-01, проверка приложением); для AD — sAMAccountName или UPN, обновляется при входе |
| email | CITEXT | | NULL | `CHECK (char_length(email) <= 254)`; уникален среди не-NULL: `CREATE UNIQUE INDEX users_email_uq ON users (email) WHERE email IS NOT NULL` |
| full_name | VARCHAR(200) | ✓ | — | ФИО |
| timezone | TEXT | | NULL | IANA; NULL — пояс приложения (FR-UI-02) |
| source | `user_source` ENUM('local','ad') | ✓ | 'local' | |
| ad_object_guid | UUID | | NULL | `UNIQUE`; только для `source = 'ad'`: `CHECK (source = 'ad' OR ad_object_guid IS NULL)` |
| password_hash | TEXT | | NULL | Argon2id (SEC-AUTH-01); `CHECK (source = 'local' OR password_hash IS NULL)` |
| password_changed_at | TIMESTAMPTZ | | NULL | |
| totp_secret_enc | BYTEA | | NULL | AES-256-GCM с идентификатором ключа (SEC-CRYPT-02/03) |
| totp_enabled | BOOLEAN | ✓ | false | `CHECK (NOT totp_enabled OR totp_secret_enc IS NOT NULL)` |
| status | `user_status` ENUM('active','blocked','pending_password','anonymized') | ✓ | 'pending_password' | |
| block_reason | `user_block_reason` ENUM('manual','ad_disabled','ad_group','ad_missing','not_matched') | | NULL | `CHECK ((status = 'blocked') = (block_reason IS NOT NULL))` |
| blocked_at | TIMESTAMPTZ | | NULL | Раздел 4 (BR-PRJ-07, FR-ADM-05) |
| last_login_at | TIMESTAMPTZ | | NULL | |
| notify_digest | BOOLEAN | ✓ | true | Ежедневная сводка |
| notify_questions | BOOLEAN | ✓ | true | Пачки писем о вопросах (FR-NOTIF-02) |
| last_digest_at | TIMESTAMPTZ | | NULL | Раздел 4: момент последней сводки (FR-NOTIF-02 «только если есть новые события с прошлого письма») |
| anonymized_no | INTEGER | | NULL | Раздел 4: номер «Удалённый пользователь #N» (SEC-PD-03); `UNIQUE`, из последовательности `users_anonymized_no_seq`; `CHECK ((status = 'anonymized') = (anonymized_no IS NOT NULL))` |

`created_by` у `users` — кто завёл учётку (администратор, модератор из AD-поиска, `NULL` — JIT-вход или консоль).
Он нужен для пометки «администратор назначил свою учётку» (BR-ADM-03, `project_members.added_by_admin_self`).

Счётчики неудачных входов и блокировки — в Redis по паре «логин + IP» (DB-D05, ключ `lock:{login}:{ip}`).
Зарезервированность логинов суперадминистраторов (FR-AUTH-AD-12) проверяется по `user_roles.role = 'superadmin'`
без учёта регистра (`login` — CITEXT).

#### `user_roles`

| Столбец | Тип | NN | По умолчанию | Смысл |
|---|---|---|---|---|
| user_id | UUID | ✓ | — | → `users` |
| role | `system_role` ENUM('superadmin','admin','moderator','presale','presale_head','security_auditor') | ✓ | — | Роль «Пользователь» не хранится |
| source | `role_source` ENUM('manual','ad_group') | ✓ | 'manual' | `CHECK (source = 'manual' OR role IN ('moderator','presale'))` (FR-AUTH-AD-07) |
| created_at, created_by | | ✓ / | now() / — | Кто выдал (G-4); `updated_*` нет — строка не меняется, а удаляется и вставляется |

PK (`user_id`, `role`). Совместимость ролей (BR-ROLE-02: superadmin — без других ролей; security_auditor —
только с «Пользователь») и предел 2–3 суперадминистратора (BR-ROLE-03, 409 `LAST_SUPERADMIN` / `SUPERADMIN_LIMIT`)
проверяет приложение в транзакции с блокировкой `SELECT … FOR UPDATE` строк ролей `superadmin`.
Индекс: `user_roles (role)`.

#### `password_history`

`id UUID PK`, `user_id UUID NN → users`, `password_hash TEXT NN`, `created_at TIMESTAMPTZ NN DEFAULT now()`.
Индекс (`user_id`, `created_at DESC`). Хранятся последние N (`security.password_policy.history`, по умолчанию 5);
лишние удаляет сервис паролей в той же транзакции. При переходе «Приложение → AD» строки пользователя удаляются
(FR-AUTH-SW-01).

#### `backup_codes`

`id UUID PK`, `user_id UUID NN → users`, `code_hash TEXT NN` (Argon2id или HMAC-SHA-256 с ключом приложения —
выбор AUTH-006), `created_at TIMESTAMPTZ NN DEFAULT now()`, `used_at TIMESTAMPTZ NULL`.
Индекс (`user_id`) `WHERE used_at IS NULL`. Новый набор (POST `/me/backup-codes`) удаляет старые строки пользователя.

#### `totp_used_codes` — в Redis (DB-D02)

Таблицы нет. Ключ `totp:used:{user_id}:{time_step}`, значение `1`, TTL 120 с, запись `SET NX`
(повтор → отказ, FR-2FA-01).

#### `known_devices`

`user_id UUID NN → users`, `ua_family TEXT NN` (семейство браузера, например `Chrome`), `subnet CIDR NN`
(IPv4 /24 или IPv6 /64), `first_seen_at TIMESTAMPTZ NN DEFAULT now()`, `last_seen_at TIMESTAMPTZ NN`.
PK (`user_id`, `ua_family`, `subnet`). Устройство «новое», если строки нет или `last_seen_at` старше 90 дней
(FR-NOTIF-02, SEC-AUTH-06).

#### `sessions`

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id_hash | BYTEA | ✓ | PK; SHA-256 идентификатора сессии (сам идентификатор — только в cookie и Redis) |
| user_id | UUID | ✓ | → `users` |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| last_seen_at | TIMESTAMPTZ | ✓ | Последняя активность (только запросы без `X-Background: 1`, FR-SESS-02); переносится из Redis не чаще раза в минуту |
| expires_at | TIMESTAMPTZ | ✓ | Абсолютный срок (12 ч по умолчанию) |
| ip | INET | ✓ | |
| user_agent | VARCHAR(512) | | Обрезается до 512 символов |
| mfa_passed | BOOLEAN | ✓ | DEFAULT false; TOTP пройден в этой сессии (FR-2FA-05) |
| step_up_until | TIMESTAMPTZ | | Step-up действует до (SEC-AUTH-05, 5 минут) |
| revoked_at | TIMESTAMPTZ | | Отзыв (выход, блокировка, смена пароля, проверка AD) |
| revoke_reason | TEXT | | Раздел 4: причина завершения для аудита и списка сессий (`logout`, `expired`, `user_revoked`, `blocked`, `password_changed`, `ad_check`, `mode_switch`, `superseded`) |

Индексы: (`user_id`) `WHERE revoked_at IS NULL`; (`expires_at`). Источник истины для проверки сессии на каждом
запросе — Redis (FR-SESS-01); таблица — для списка сессий (FR-SESS-04) и аудита. При идентификаторе, сменённом
при входе и прохождении TOTP (FR-SESS-03), старая строка закрывается с `revoke_reason = 'superseded'`, создаётся новая.

#### `system_settings`

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| key | TEXT | ✓ | PK; `CHECK (key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')`. Перечень ключей и схемы значений — `contracts/settings.schema.json` (ADM-000) |
| value | JSONB | ✓ | Значение по схеме ключа. Секрет хранится как `{"enc": "<base64 AES-256-GCM>", "kid": "<id ключа>"}` (SEC-CRYPT-02/03); открытого значения в БД нет |
| updated_by | UUID | | → `users`; NULL — консоль или мастер установки до появления пользователя |
| updated_at | TIMESTAMPTZ | ✓ | DEFAULT now() |

Группы ключей (14.2): `auth.mode`, `auth.ad.*`, `security.password_policy`, `security.session`, `security.lockout`,
`security.mfa_policy`, `security.admin_networks`, `security.alert_email`, `smtp.*`, `siem.*`, `app.base_url`,
`app.timezone`, `retention.*`, `digest.time`, `method.*` (DB-D01). Признак завершения мастера установки —
ключ из той же схемы ADM-000.

### 2.2. Справочники (DB-004)

Все справочники — [А]; удаление логическое через `is_active` (G-6), кроме `work_calendar` (строки дат) и
`discipline_profiles` (удаляется, если не используется ни одним проектом).

#### `phases` [А]

`id UUID PK`, `name VARCHAR(100) NN`, `sort_order INTEGER NN`, `is_cross_cutting BOOLEAN NN DEFAULT false`,
`is_active BOOLEAN NN DEFAULT true`.
Ровно одна сквозная фаза: `CREATE UNIQUE INDEX phases_one_cross_cutting ON phases ((true)) WHERE is_cross_cutting`
(«не больше одной»; «хотя бы одна» гарантирует миграция данных DB-010 и запрет снятия флага в ADM-007).
Индекс (`sort_order`). Сквозная фаза — «Управление проектом» (6.3).

#### `disciplines` [А]

`id UUID PK`, `name VARCHAR(100) NN UNIQUE`, `short_name VARCHAR(12) NN` (7.5: ≤ 12 символов), `color VARCHAR(7) NN`
(`CHECK (color ~ '^#[0-9A-Fa-f]{6}$')`), `default_profile_id UUID NULL → discipline_profiles` (`DEFERRABLE INITIALLY
DEFERRED`: профиль и дисциплина создаются в одной транзакции), `is_active BOOLEAN NN DEFAULT true`.

#### `node_types` [А]

| Столбец | Тип | NN | По умолчанию | Смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| name | VARCHAR(50) | ✓ | — | Название (NFR-LIM-01: локальный тип — 50) |
| icon | TEXT | ✓ | — | Ключ иконки из курируемого набора фронтенда (FR-TREE-03, GAP-07); сервер принимает только ключи из набора |
| norms | JSONB | ✓ | '[]' | `[{"label":"средний","o":"5","r":"7","p":"10"}]` — значения строками (G-9); `CHECK (jsonb_typeof(norms) = 'array')` |
| is_active | BOOLEAN | ✓ | true | `CHECK (NOT is_system OR is_active)` — «Работа» не отключается |
| is_system | BOOLEAN | ✓ | false | Тип «Работа» (BR-TREE-08); ровно один: `UNIQUE INDEX … ((true)) WHERE is_system` |
| project_id | UUID | | NULL | → `projects` `ON DELETE CASCADE`; не NULL — локальный тип проекта |
| proposal_status | `node_type_proposal` ENUM('none','proposed','accepted','merged','rejected') | ✓ | 'none' | `CHECK ((project_id IS NULL) = (proposal_status IN ('none','accepted')))`: глобальный тип — `none` или `accepted` (принятый локальный становится глобальным: `project_id := NULL`), локальный — `proposed`, `merged`, `rejected` |
| merged_into_id | UUID | | NULL | Раздел 4: → `node_types`; тип, с которым объединён (FR-TREE-03); `CHECK ((proposal_status = 'merged') = (merged_into_id IS NOT NULL))` |

Индексы: (`project_id`) `WHERE project_id IS NOT NULL`; (`proposal_status`) `WHERE proposal_status = 'proposed'`.

#### `discipline_profiles` [А]

`id UUID PK`, `discipline_id UUID NN → disciplines`, `name VARCHAR(100) NN`, `type_chain UUID[] NN`
(`CHECK (cardinality(type_chain) BETWEEN 1 AND 8)`; элементы — `node_types.id`, проверка приложением, потому что
у массива нет внешнего ключа). `UNIQUE (discipline_id, name)`. «Один профиль по умолчанию у дисциплины» хранится
в `disciplines.default_profile_id`.

#### `comment_tags` [А]

`id UUID PK`, `name VARCHAR(50) NN`, `short_name VARCHAR(12) NN`, `color VARCHAR(7) NN`,
`category comment_tag_category ENUM('assumption','constraint','risk','tech') NN`, `is_active BOOLEAN NN DEFAULT true`.

#### `control_ratios` [А]

`id UUID PK`, `discipline_a_id UUID NN → disciplines`, `disciplines_b UUID[] NN` (`CHECK (cardinality(disciplines_b) >= 1)`),
`min_pct NUMERIC(5,2) NN`, `max_pct NUMERIC(5,2) NN`, `is_active BOOLEAN NN DEFAULT true`;
`CHECK (0 <= min_pct AND min_pct <= max_pct AND max_pct <= 999.99)`.

#### `app_params` — в `system_settings` (DB-D01)

Ключи `method.*`: пороги «крупного листа» для «Средне» (80 ч) и «Детально» (40 ч), ожидаемое число единиц для
«Средне», % УП по умолчанию (18), срок автоархивации (180 дней, 0 — выключено). Точные имена и схема — ADM-000.

#### `work_calendar` [А]

`date DATE PK`, `is_working BOOLEAN NN`, `year SMALLINT NN` (`CHECK (year = EXTRACT(YEAR FROM date))`).
Индекс (`year`). Хранятся все дни загруженного года; если строк за год нет — Пн–Пт (BR-PRJ-08, Q-43).

#### `loss_reasons` [А]

`id UUID PK`, `name VARCHAR(100) NN`, `is_other BOOLEAN NN DEFAULT false` (раздел 4: «Другое» требует текст,
BR-PRJ-05), `is_active BOOLEAN NN DEFAULT true`.

#### `vat_rates` [А]

`id UUID PK`, `name VARCHAR(50) NN`, `percent NUMERIC(5,2) NULL` (NULL — «без НДС»; `CHECK (percent IS NULL OR percent BETWEEN 0 AND 100)`),
`is_active BOOLEAN NN DEFAULT true`, `is_default BOOLEAN NN DEFAULT false`;
`CHECK (NOT is_default OR is_active)`; ровно одна по умолчанию — `UNIQUE INDEX vat_rates_one_default ON vat_rates ((true)) WHERE is_default`
(C-31). «Без НДС» неудаляема: строка с `percent IS NULL` не деактивируется (проверка ADM-007).

#### `currencies` [А]

`code CHAR(3) PK` (`CHECK (code ~ '^[A-Z]{3}$')`, ISO 4217), `symbol VARCHAR(8) NN`, `is_active BOOLEAN NN DEFAULT true`;
`CHECK (code <> 'RUB' OR is_active)` — RUB неудаляема (7.5).

### 2.3. Проекты, деньги, команда (DB-005)

#### `projects` [А]

| Столбец | Тип | NN | По умолчанию | Ограничения и смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| name | VARCHAR(200) | ✓ | — | `CHECK (char_length(name) >= 3)` (FR-PRJ-01: 3–200) |
| customer | VARCHAR(200) | ✓ | — | `CHECK (char_length(customer) >= 1)` |
| description | VARCHAR(10000) | ✓ | '' | |
| next_question_no | INTEGER | ✓ | 1 | `CHECK (next_question_no >= 1)`; выдаётся `UPDATE … RETURNING` в транзакции создания вопроса заказчику |
| status | `project_status` ENUM('preparation','estimation','consolidation','completed','archived') | ✓ | 'preparation' | |
| outcome | `project_outcome` ENUM('unknown','won','lost','cancelled') | ✓ | 'unknown' | BR-PRJ-05 |
| loss_reason_id | UUID | | NULL | → `loss_reasons`; `CHECK (outcome = 'lost' OR loss_reason_id IS NULL)` |
| loss_reason_text | VARCHAR(500) | | NULL | Обязателен, если причина — «Другое» (проверка приложением) |
| quote_figure | `quote_figure` ENUM('e','p80','p90') | ✓ | 'p80' | BR-MONEY-06 |
| duration_weeks | SMALLINT | | NULL | `CHECK (duration_weeks BETWEEN 1 AND 260)` (BR-PRJ-06) |
| no_moderator_since | TIMESTAMPTZ | | NULL | BR-PRJ-07 |
| detail_level | `detail_level` ENUM('coarse','medium','detailed') | ✓ | 'medium' | |
| pm_percent | NUMERIC(5,2) | ✓ | — | `CHECK (pm_percent BETWEEN 0 AND 50 AND pm_percent * 2 = trunc(pm_percent * 2))` (FR-PRJ-01: 0–50, шаг 0,5) |
| pm_percent_reason | VARCHAR(1000) | ✓ | '' | FR-PRJ-01: до 1 000 |
| deadline | DATE | | NULL | Не раньше сегодняшней — проверка приложением при вводе |
| version | BIGINT | ✓ | 0 | Монотонный счётчик изменений проекта (ARCH-02); увеличивается `UPDATE … SET version = version + 1 RETURNING version` в транзакции изменения |
| completed_at | TIMESTAMPTZ | | NULL | Последний переход в «Завершена» (BR-PRJ-03) |
| archived_at | TIMESTAMPTZ | | NULL | |
| cancel_reason | VARCHAR(500) | | NULL | `CHECK (cancel_reason IS NULL OR char_length(cancel_reason) >= 10)` (FR-PRJ-05: 10–500) |
| copied_from_id | UUID | | NULL | Раздел 4: → `projects` `ON DELETE SET NULL`; источник копии (FR-PRJ-02, правило копирования ставок) |

Индексы: (`status`); (`no_moderator_since`) `WHERE no_moderator_since IS NOT NULL`; (`completed_at`)
`WHERE status = 'completed'` (автоархивация); (`created_at`) (фильтр периода портфеля, FR-PORT-01).

#### `project_money` [А по `updated_*`] — доступ только через сервис денег (G-11)

`project_id UUID PK → projects ON DELETE CASCADE`, `currency CHAR(3) NN DEFAULT 'RUB' → currencies(code)`,
`exchange_rate NUMERIC(12,4) NN DEFAULT 1` (`CHECK (exchange_rate > 0)`, `CHECK (currency <> 'RUB' OR exchange_rate = 1)`),
`vat_rate_id UUID NN → vat_rates`, `vat_percent NUMERIC(5,2) NULL` (копия процента на момент выбора; NULL — «без НДС»),
`contract_amount NUMERIC(20,0) NULL` (`CHECK (contract_amount >= 0)`; в валюте КП, BR-PRJ-05), `updated_by`, `updated_at`.
Строка создаётся вместе с проектом.

#### `project_totals` — кэш для списков (ARCH-03)

`project_id UUID PK → projects ON DELETE CASCADE`, `e`, `p80`, `p90` — `NUMERIC(14,2) NULL`,
`cost_rub NUMERIC(20,0) NULL` (по E без НДС), `quote_rub NUMERIC(20,0) NULL`, `quote_cur NUMERIC(20,0) NULL`
(по «Цифре для КП» без НДС, в ₽ и в валюте КП), `rates_missing BOOLEAN NN DEFAULT false` (раздел 4: «не заданы ставки»,
BR-MONEY-02, для реестра портфеля), `project_version BIGINT NN` (раздел 4: версия проекта, по которой посчитан кэш),
`updated_at TIMESTAMPTZ NN`.
`NULL` в часах или деньгах — значение не поместилось в тип или не вычисляется (в списке «—», 14.2 «Проверка
переполнения», BR-MONEY-04). Денежные столбцы отдаются только с `money.read` (FR-HOME-04).

#### `project_totals_daily` (GAP-01)

`project_id UUID NN → projects ON DELETE CASCADE`, `date DATE NN`, `e`, `p80`, `p90`, `cost_rub`, `quote_rub`,
`quote_cur` — типы и смысл как в `project_totals`, `updated_at TIMESTAMPTZ NN`. PK (`project_id`, `date`).
Задача обновления кэша делает `INSERT … ON CONFLICT (project_id, date) DO UPDATE` для текущего дня по `app.timezone`.

#### `project_rates` [А]

`id UUID PK`, `project_id UUID NN → projects ON DELETE CASCADE`, `discipline_id UUID NULL → disciplines`
(NULL — ставка УП), `rate_rub NUMERIC(12,0) NN` (`CHECK (rate_rub BETWEEN 0 AND 1000000)`, FR-PRJ-01).
`UNIQUE NULLS NOT DISTINCT (project_id, discipline_id)` (DB-D03). Нет строки — ставка не задана (BR-MONEY-02).

#### `project_members` [А]

| Столбец | Тип | NN | По умолчанию | Смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| project_id | UUID | ✓ | — | → `projects` CASCADE |
| user_id | UUID | ✓ | — | → `users` |
| role | `project_role` ENUM('moderator','expert','presale') | ✓ | — | |
| discipline_id | UUID | | NULL | → `disciplines`; `CHECK ((role = 'expert') = (discipline_id IS NOT NULL))` |
| is_reviewer | BOOLEAN | ✓ | false | `CHECK (NOT is_reviewer OR role = 'expert')` |
| added_by_admin_self | BOOLEAN | ✓ | false | Администратор назначил себя или свою учётку (BR-ADM-03) |
| notified_at | TIMESTAMPTZ | | NULL | Раздел 4: когда ушло «Вас назначили» (BR-PRJ-01: назначенным в «Подготовке» — при запуске оценки) |

`UNIQUE NULLS NOT DISTINCT (project_id, user_id, role, discipline_id)` (DB-D03). Индексы: (`user_id`)
(«Мои оценки»); (`project_id`, `role`). «Последний модератор» (409 `LAST_MODERATOR`, BR-ROLE-07) и «0–3 пресейла»
проверяет приложение под `SELECT … FOR UPDATE` строки `projects`.

#### `project_phases`

`project_id UUID NN → projects CASCADE`, `phase_id UUID NN → phases`, `is_enabled BOOLEAN NN DEFAULT true`,
`in_pm_base BOOLEAN NN DEFAULT true` (BR-CALC-05; по умолчанию — все, кроме «Гарантийной поддержки»: значение
ставит сервис создания проекта). PK (`project_id`, `phase_id`). Сквозная фаза всегда `is_enabled = true`
(проверка приложением, 5.1).

#### `project_disciplines`

`project_id UUID NN → projects CASCADE`, `discipline_id UUID NN → disciplines`, `profile_id UUID NN → discipline_profiles`
(по умолчанию `disciplines.default_profile_id`, FR-TREE-04), `created_at`, `created_by`, `updated_at`, `updated_by` (G-4).
PK (`project_id`, `discipline_id`).

#### `branch_status`

`project_id UUID NN → projects CASCADE`, `phase_id UUID NN → phases`, `discipline_id UUID NN → disciplines`,
`status branch_status_value ENUM('not_started','draft','done','not_needed') NN DEFAULT 'not_started'`,
`changed_by UUID NULL → users` (NULL — «Система»), `changed_at TIMESTAMPTZ NN DEFAULT now()`.
PK (`project_id`, `phase_id`, `discipline_id`) — ровно один статус на пару «фаза × дисциплина» (BR-BR-03).

#### `support_sessions`

`id UUID PK`, `admin_id UUID NN → users`, `project_id UUID NN → projects CASCADE`, `reason VARCHAR(500) NN`
(`CHECK (char_length(reason) >= 10)`, FR-ADM-06), `started_at TIMESTAMPTZ NN DEFAULT now()`,
`expires_at TIMESTAMPTZ NN` (`CHECK (expires_at <= started_at + interval '60 minutes')`),
`ended_at TIMESTAMPTZ NULL` (раздел 4: досрочное закрытие). Индекс (`admin_id`, `project_id`, `expires_at`).

### 2.4. Дерево, история, версии (DB-006)

#### `nodes` [А]

| Столбец | Тип | NN | По умолчанию | Ограничения и смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| project_id | UUID | ✓ | — | → `projects` CASCADE |
| parent_id | UUID | | NULL | → `nodes`; NULL только у узлов-фаз |
| kind | `node_kind` ENUM('phase','discipline','item') | ✓ | — | |
| phase_id | UUID | ✓ | — | → `phases`; денормализовано для всех узлов |
| discipline_id | UUID | | NULL | → `disciplines`; денормализовано для всех узлов ниже фазы |
| type_id | UUID | | NULL | → `node_types`; для `item` (NULL трактуется как «Работа», BR-TREE-08) |
| title | VARCHAR(200) | ✓ | — | `CHECK (char_length(title) >= 1 AND title !~ '[\r\n]')` (BR-TREE-07; обрезка пробелов — приложением) |
| position | TEXT COLLATE "C" | ✓ | — | Ключ порядка среди соседей (fractional indexing, ARCH-04) |
| o, r, p | NUMERIC(10,2) | | NULL | `CHECK (x IS NULL OR (x BETWEEN 0 AND 99999.5 AND x * 2 = trunc(x * 2)))` для каждого (BR-CALC-03: шаг 0,5) |
| multiplier | INTEGER | ✓ | 1 | `CHECK (multiplier BETWEEN 1 AND 10000)` |
| comment_lines | JSONB | | NULL | `[{"tag_id": "<uuid>" \| null, "text": "…"}]`, до 10 строк, суммарно до 2 000 символов (R-03); `CHECK (comment_lines IS NULL OR jsonb_typeof(comment_lines) = 'array')`, длины — приложением |
| reviewed_by | UUID | | NULL | → `users`; «Проверено» |
| reviewed_at | TIMESTAMPTZ | | NULL | `CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL))` |
| self_review | BOOLEAN | ✓ | false | FR-REV-04; `CHECK (NOT self_review OR reviewed_by IS NOT NULL)` |
| version | INTEGER | ✓ | 1 | Версия узла (FR-TREE-32) |
| field_versions | JSONB | ✓ | '{}' | Версия узла, на которой поле менялось последний раз. Ключи: `title`, `type`, `o`, `r`, `p`, `multiplier`, `comment`, `parent` (перенос и порядок), `review` |
| deleted_at | TIMESTAMPTZ | | NULL | Корзина (FR-TREE-24) |
| deleted_batch_id | UUID | | NULL | Пакет удаления; `CHECK ((deleted_at IS NULL) = (deleted_batch_id IS NULL))` |
| deleted_by | UUID | | NULL | Раздел 4: → `users`; кто удалил (корзина эксперта — «удалённое из своих веток», FR-TREE-24) |

Ограничения строки:

- `CHECK (kind <> 'item' OR (phase_id IS NOT NULL AND discipline_id IS NOT NULL))` (14.2);
- `CHECK ((kind = 'phase') = (parent_id IS NULL))` — parent NULL только у фаз (14.2);
- `CHECK (kind <> 'phase' OR (discipline_id IS NULL AND o IS NULL AND r IS NULL AND p IS NULL))` — фаза не дисциплина и не лист;
- `CHECK (kind <> 'discipline' OR discipline_id IS NOT NULL)`;
- `CHECK (kind = 'item' OR type_id IS NULL)`.

Признак «лист» не хранится (нет живых детей); `O/R/P` у узла с детьми запрещены приложением
(422 `NODE_HAS_CHILDREN`, BR-TREE-01). Ветка дисциплины может быть листом (BR-TREE-04). Глубина ≤ 8 ниже ветки и
лимит 5 000 живых узлов — приложением под `SELECT … FOR UPDATE` строки `projects` (BR-TREE-05/06, 422 `DEPTH_LIMIT`,
409 `NODES_LIMIT`).

Индексы (14.3 и уникальность системных узлов):

- `nodes_project_live_idx ON nodes (project_id) WHERE deleted_at IS NULL`;
- `nodes_parent_position_idx ON nodes (parent_id, position)`;
- `nodes_batch_idx ON nodes (project_id, deleted_batch_id) WHERE deleted_at IS NOT NULL` (корзина);
- `UNIQUE (project_id, phase_id) WHERE kind = 'phase' AND deleted_at IS NULL`;
- `UNIQUE (project_id, phase_id, discipline_id) WHERE kind = 'discipline' AND deleted_at IS NULL`.

Запрос загрузки дерева — 14.3 без изменений.

#### `node_history` — только INSERT (G-5)

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| node_id | UUID | ✓ | → `nodes` CASCADE |
| project_id | UUID | ✓ | → `projects` CASCADE |
| project_version | BIGINT | ✓ | Версия проекта после изменения |
| node_version | INTEGER | ✓ | Раздел 4: версия узла после изменения (кнопка «Вернуть это значение», FR-TREE-25) |
| user_id | UUID | | → `users`; NULL — «Система» |
| action | `node_action` ENUM('create','update','move','delete','restore','split','collapse','review') | ✓ | |
| changes | JSONB | ✓ | `{"<поле>": [<было>, <стало>]}`; поля — ключи `field_versions` и `phase_id`/`discipline_id` для переноса; десятичные — строками (G-9): `{"r":["12","16"],"p":["20","30"]}` |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |

Индекс `node_history (node_id, created_at)` (14.3); (`project_id`, `user_id`, `created_at`) — метрики пилота GAP-04.

#### `change_log`

`project_id UUID NN → projects CASCADE`, `version BIGINT NN`, `event JSONB NN` (событие в формате
`contracts/ws-events.schema.json` без денежных полей; денежные события в `change_log` не пишутся — клиент с правом
перезапрашивает `/money`), `created_at TIMESTAMPTZ NN DEFAULT now()`. PK (`project_id`, `version`).
Очистка старше 7 дней (`retention.change_log_days`, NFR-REL-06); при запросе версии старше хранимой —
`resync.required` (ARCH-02).

#### `user_view_state`

`user_id UUID NN → users`, `project_id UUID NN → projects CASCADE`, `state JSONB NN DEFAULT '{}'`
(раскрытие, фильтры, ширины; размер ≤ 64 КБ — приложением), `updated_at TIMESTAMPTZ NN DEFAULT now()`.
PK (`user_id`, `project_id`).

### 2.5. Обсуждения, заметки, уведомления (DB-007)

#### `threads` [А]

| Столбец | Тип | NN | По умолчанию | Смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| project_id | UUID | ✓ | — | → `projects` CASCADE |
| node_id | UUID | | NULL | → `nodes` CASCADE; NULL — обсуждение уровня проекта |
| opened_by | UUID | ✓ | — | → `users` |
| status | `thread_status` ENUM('open','resolved') | ✓ | 'open' | Обычный вопрос (FR-DISC-09) |
| resolved_by, resolved_at | UUID, TIMESTAMPTZ | | NULL | |
| is_customer | BOOLEAN | ✓ | false | Вопрос заказчику |
| customer_question_no | INTEGER | | NULL | `CHECK ((is_customer) = (customer_question_no IS NOT NULL))` |
| customer_status | `customer_question_status` ENUM('new','sent','answered','closed','withdrawn') | | NULL | `CHECK ((is_customer) = (customer_status IS NOT NULL))` |
| sent_at, answered_at | TIMESTAMPTZ | | NULL | |
| closed_by, closed_at | UUID, TIMESTAMPTZ | | NULL | `closed` (BR-CQ-02) |
| withdraw_reason | VARCHAR(500) | | NULL | `CHECK (customer_status IS DISTINCT FROM 'withdrawn' OR withdraw_reason IS NOT NULL)` |
| edited_after_sent | BOOLEAN | ✓ | false | BR-CQ-01 |

Индексы: `threads (project_id) WHERE status = 'open'` (14.3); `UNIQUE (project_id, customer_question_no) WHERE is_customer`
(14.3, FR-CQ-02); (`node_id`).

#### `messages`

| Столбец | Тип | NN | По умолчанию | Смысл |
|---|---|---|---|---|
| id | UUID | ✓ | — | PK |
| project_id | UUID | ✓ | — | → `projects` CASCADE |
| node_id | UUID | | NULL | → `nodes` CASCADE; NULL — уровень проекта |
| thread_id | UUID | | NULL | → `threads` CASCADE; сообщение-вопрос и ответы на него |
| author_id | UUID | | — | → `users`; NULL только у `kind = 'event'` от «Системы» |
| body | VARCHAR(10000) | ✓ | — | `CHECK (kind = 'event' OR char_length(body) >= 1)`; `CHECK (kind = 'customer_answer' OR char_length(body) <= 4000)` (FR-DISC-02) |
| kind | `message_kind` ENUM('message','event','customer_answer') | ✓ | 'message' | |
| event | JSONB | | NULL | Раздел 4: структура серого события ленты FR-DISC-07 (`{"action":"update","changes":{…}}`); `CHECK ((kind = 'event') = (event IS NOT NULL))` |
| needs_answer | BOOLEAN | ✓ | false | |
| created_at | TIMESTAMPTZ | ✓ | now() | |
| edited_at | TIMESTAMPTZ | | NULL | Метка «изменено» |
| edited_by | UUID | | NULL | Раздел 4: → `users`; правка модератором или пресейлом после отправки (BR-CQ-01) |
| revoked_at | TIMESTAMPTZ | | NULL | «Сообщение отозвано автором»; при выдаче тело заменяется пометкой (FR-DISC-06) |

Индексы: `messages (node_id, created_at)` (14.3); (`thread_id`, `created_at`); (`project_id`, `created_at`)
`WHERE node_id IS NULL` (лента проекта).

#### `message_history` — только INSERT (G-5)

`id UUID PK`, `message_id UUID NN → messages CASCADE`, `body VARCHAR(10000) NN` (текст до правки или отзыва),
`edited_by UUID NN → users`, `edited_at TIMESTAMPTZ NN DEFAULT now()`,
`reason message_history_reason ENUM('edit','revoke','edit_after_sent') NN`. Индекс (`message_id`, `edited_at`).

#### `project_notes` [А] — доступ только с `notes.read` / `notes.write` (SEC-AUTHZ-04)

`id UUID PK`, `project_id UUID NN → projects CASCADE`, `node_id UUID NULL → nodes CASCADE`, `author_id UUID NN → users`,
`body VARCHAR(4000) NN` (`CHECK (char_length(body) >= 1)`), `created_at TIMESTAMPTZ NN DEFAULT now()`,
`edited_at TIMESTAMPTZ NULL`. Индекс (`project_id`, `node_id`, `created_at`). В снимки и экспорт не попадают (FR-NOTE-01).

#### `customer_documents` [А]

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| project_id | UUID | ✓ | → `projects` CASCADE |
| file_name | VARCHAR(255) | ✓ | Исходное имя (выдаётся в `Content-Disposition`) |
| mime | TEXT | ✓ | `CHECK (mime IN ('application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))` — по сигнатуре (SEC-WEB-10) |
| size_bytes | BIGINT | ✓ | `CHECK (size_bytes BETWEEN 1 AND 52428800)` (50 МБ) |
| storage_key | UUID | ✓ | `UNIQUE`; имя файла на томе |
| key_enc | BYTEA | ✓ | Ключ файла под мастер-ключом (SEC-CRYPT-06) |
| scan_status | `scan_status` ENUM('pending','clean','infected','error') | ✓ | DEFAULT 'pending' |
| uploaded_by | UUID | ✓ | → `users` |
| uploaded_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| deleted_at | TIMESTAMPTZ | | Корзина 30 дней (FR-DOC-01) |
| deleted_by | UUID | | Раздел 4: → `users` |

Индекс (`project_id`) `WHERE deleted_at IS NULL`. Лимит 1 ГБ на проект — приложением: сумма `size_bytes` по
`scan_status IN ('pending','clean')` (11.7 №4).

#### `support_sessions` — см. 2.3.

#### `message_addressees`

`message_id UUID NN → messages CASCADE`, `target_type addressee_type ENUM('user','discipline','moderators','customer') NN`,
`target_id UUID NULL` (`users.id` или `disciplines.id`); `CHECK ((target_type IN ('user','discipline')) = (target_id IS NOT NULL))`.
`UNIQUE NULLS NOT DISTINCT (message_id, target_type, target_id)`. Индекс (`target_type`, `target_id`) — «вопросы мне» и
переадресация при замене участника (FR-ADM-05).

#### `notifications`

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| user_id | UUID | ✓ | → `users` |
| project_id | UUID | | → `projects` CASCADE; NULL — уведомление вне проекта (например, администратору) |
| node_id | UUID | | → `nodes` ON DELETE SET NULL |
| kind | TEXT | ✓ | Вид из `contracts/notifications.yaml` (DB-D06) |
| payload | JSONB | ✓ | DEFAULT '{}'; без денег (14.2); состав по виду — NTF-001 |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| read_at | TIMESTAMPTZ | | |
| emailed_at | TIMESTAMPTZ | | Отправлено пачкой писем (FR-NOTIF-02) |

Индексы: `notifications (user_id) WHERE read_at IS NULL` (14.3); (`user_id`, `created_at DESC`);
(`created_at`) — очистка старше 1 года (NFR-REL-06).

### 2.6. Снимки, экспорт, аудит (DB-008, DB-009)

#### `snapshots`

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| project_id | UUID | ✓ | → `projects` CASCADE |
| name | VARCHAR(100) | ✓ | `CHECK (char_length(name) >= 1)` |
| description | VARCHAR(1000) | ✓ | DEFAULT '' |
| project_version | BIGINT | ✓ | Раздел 4: версия проекта на момент снимка |
| created_by | UUID | ✓ | → `users` |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| is_invalid | BOOLEAN | ✓ | DEFAULT false; «ошибочный» (FR-SNAP-02) |
| invalidated_by, invalidated_at | UUID, TIMESTAMPTZ | | Раздел 4 |
| payload | JSONB | ✓ | Дерево, расчёты (часы), настройки, денормализованные названия справочников, комментарии, открытые вопросы заказчику (FR-SNAP-01, BR-ADM-02). Без денег |
| money_payload | JSONB | | Ставки, валюта, курс, НДС, стоимости; отдаётся только с `money.read` (SEC-AUTHZ-04) |
| payload_sha256 | BYTEA | ✓ | SHA-256 канонического JSON (RFC 8785) объединения `payload` и `money_payload` |

Права `estimator_app`: `INSERT`, `SELECT`, `UPDATE (is_invalid, invalidated_by, invalidated_at)`; без `DELETE`
(кроме `project purge` — роль `estimator_migrator`). Индекс (`project_id`, `created_at`). Формат `payload` — схема
`contracts/snapshot.schema.json` (задача CORE-060).

#### `export_files`

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| user_id | UUID | ✓ | → `users`; файл доступен только ему (FR-EXP-05) |
| project_id | UUID | | → `projects` CASCADE; NULL — выгрузка вне проекта (портфель, аудит) |
| kind | TEXT | ✓ | Вид из `contracts/exports.yaml` (DB-D06) |
| snapshot_id | UUID | | Раздел 4: → `snapshots` CASCADE; источник «снимок» (FR-EXP-03) |
| status | `export_status` ENUM('pending','ready','failed') | ✓ | Раздел 4: DEFAULT 'pending' («Готовим файл…», FR-EXP-05) |
| file_name | VARCHAR(255) | | Раздел 4: имя для скачивания (FR-EXP-03) |
| path | TEXT | | Путь на томе экспорта; заполнен при `ready` |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| expires_at | TIMESTAMPTZ | ✓ | `created_at + 24 h` (NFR-REL-06) |

Индексы: (`user_id`, `created_at DESC`); (`expires_at`).

#### `audit.audit_log` — только INSERT (G-5), схема `audit`

| Столбец | Тип | NN | Смысл (SEC-AUD-02) |
|---|---|---|---|
| id | BIGINT | ✓ | `GENERATED ALWAYS AS IDENTITY`; порядок цепочки. Исключение из G-2: для цепочки нужен строгий порядок вставки |
| ts | TIMESTAMPTZ | ✓ | Время с микросекундами, UTC |
| event_type | TEXT | ✓ | Тип из `contracts/audit-events.yaml` (DB-D06) |
| result | `audit_result` ENUM('success','failure','denied') | ✓ | |
| user_id | UUID | | id на момент события (без FK) |
| login | TEXT | | Логин на момент события |
| ip | INET | | |
| user_agent | VARCHAR(512) | | |
| session_hash | BYTEA | | SHA-256 идентификатора сессии |
| object_type | TEXT | | Например `project`, `user`, `node_type` |
| object_id | TEXT | | id объекта (UUID или ключ настройки) |
| details | JSONB | ✓ | DEFAULT '{}'; без секретов и денежных значений (SEC-AUD-01, уточнение) |
| prev_hash | BYTEA | ✓ | Хэш предыдущей записи (у первой — хэш якоря или 32 нулевых байта) |
| hash | BYTEA | ✓ | `SHA-256(prev_hash ‖ канонический JSON записи без hash)` (SEC-AUD-03, RFC 8785) |

Партиционирование `PARTITION BY RANGE (ts)` по месяцам; PK (`ts`, `id`) (ключ партиции обязан входить в PK).
Партиции создаются на 3 месяца вперёд периодической задачей (DB-009). Индексы: (`ts`), (`user_id`, `ts`),
(`event_type`, `ts`). Вставка — только функцией `audit.append(…)` под `pg_advisory_xact_lock(<константа>)`, которая
читает последний `hash` и вставляет запись (SEC-AUD-03). У `estimator_app` — `EXECUTE` на функцию и `SELECT`
на таблицу, без `INSERT` напрямую, `UPDATE`, `DELETE`, `TRUNCATE`.

---

## 3. Таблицы сверх 14.2 (DB-D07)

Каждая из них хранит данные, которые требует SPEC, но для которых 14.2 не называет таблицу. Решение уровня A1
(AGENTS.md 2.4): поведение, видимое пользователю, не меняется.

#### `auth_tokens` (DB-003)

Основание: SEC-AUTH-03 («в БД хранится только SHA-256 токена, одноразовые, со сроком действия»), FR-SA-01,
FR-AUTH-LOC-01/03, FR-2FA-03, FR-AUTH-SW-01.

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK |
| user_id | UUID | ✓ | → `users` |
| kind | `auth_token_kind` ENUM('activation','password_reset') | ✓ | Активация (72 ч; у суперадминистратора из консоли — 60 мин) и сброс (60 мин) |
| token_hash | BYTEA | ✓ | `UNIQUE`; SHA-256 токена (256 бит из `secrets`) |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |
| created_by | UUID | | → `users`; NULL — консоль или «Забыли пароль» |
| expires_at | TIMESTAMPTZ | ✓ | |
| used_at | TIMESTAMPTZ | | Одноразовость |
| revoked_at | TIMESTAMPTZ | | Аннулирован новой ссылкой (`issue-activation`) или переходом в AD |

Индекс (`user_id`) `WHERE used_at IS NULL AND revoked_at IS NULL`. Временный токен второго шага входа (5 мин) и
одноразовая ссылка мастера — в Redis (раздел 5).

#### `project_journal` (CORE-032)

Основание: 11.6 №1 «Журнал проекта (все изменения настроек и команды)», 15.2 `GET /projects/{id}/journal`
(GAP-02), 12.7 уточнение («значения ставок остаются в истории проекта, доступной модераторам»), BR-PRJ-03
(запись от имени «Система»), FR-TREE-04, FR-PRJ-05. `change_log` для журнала не подходит: он чистится через 7 дней.

| Столбец | Тип | NN | Смысл |
|---|---|---|---|
| id | UUID | ✓ | PK (UUID v7 — сортировка по времени для курсора) |
| project_id | UUID | ✓ | → `projects` CASCADE |
| user_id | UUID | | → `users`; NULL — «Система» |
| action | TEXT | ✓ | Вид записи: `project.created`, `project.settings`, `project.status`, `team.changed`, `discipline.added`, `branch.profile`, `money.changed`, `outcome.changed`, `document.*`, `snapshot.*`; перечень — CORE-032 |
| is_money | BOOLEAN | ✓ | DEFAULT false; запись видна только с `money.read` (15.2) |
| changes | JSONB | ✓ | `{"<поле>": [<было>, <стало>]}`, десятичные строками (G-9) |
| created_at | TIMESTAMPTZ | ✓ | DEFAULT now() |

Только INSERT для `estimator_app` (G-5). Индекс (`project_id`, `id DESC`); `CHECK (is_money OR NOT (changes ?| array['rate_rub','exchange_rate','vat_percent','contract_amount','currency']))` — денежные ключи только в денежных записях.

#### `audit.audit_anchor` (DB-009)

Основание: SEC-AUD-04 («с сохранением хэша последней удалённой записи (якорь цепочки)»).
`id SMALLINT PK CHECK (id = 1)` (одна строка), `last_purged_id BIGINT NN`, `last_purged_hash BYTEA NN`,
`purged_until TIMESTAMPTZ NN`, `purged_at TIMESTAMPTZ NN`. Пишет только `estimator_audit_purge`;
`estimator_app` — `SELECT`.

---

## 4. Столбцы сверх 14.2 (DB-D08)

| Таблица.столбец | Зачем | Основание |
|---|---|---|
| `users.blocked_at` | Срок «участник заблокирован», «дней без модератора» | FR-ADM-05, BR-PRJ-07 |
| `users.last_digest_at` | Сводка «только если есть новые события с прошлого письма» | FR-NOTIF-02 |
| `users.anonymized_no` | Номер в «Удалённый пользователь #N» | SEC-PD-03 |
| `sessions.revoke_reason` | Причина завершения в списке сессий и аудите | FR-SESS-04, SEC-AUD-01 |
| `node_types.merged_into_id` | С каким типом объединён локальный тип | FR-TREE-03 |
| `loss_reasons.is_other` | «Другое» требует текст причины | BR-PRJ-05 |
| `projects.copied_from_id` | Источник копии; ставки копирует только модератор исходного проекта | FR-PRJ-02 |
| `project_totals.rates_missing`, `project_totals.project_version` | «не заданы ставки» в реестре; актуальность кэша | BR-MONEY-02, FR-PORT-01, ARCH-03 |
| `project_members.notified_at` | Письмо «Вас назначили» уходит при запуске оценки один раз | BR-PRJ-01 |
| `support_sessions.ended_at` | Досрочное закрытие режима поддержки | FR-ADM-06 |
| `nodes.deleted_by` | Эксперт видит в корзине удалённое из своих веток | FR-TREE-24 |
| `node_history.node_version` | «Вернуть это значение» и сопоставление с `field_versions` | FR-TREE-25, FR-TREE-32 |
| `messages.event`, `messages.edited_by` | Структура серого события; кто правил после отправки | FR-DISC-07, BR-CQ-01 |
| `customer_documents.deleted_by` | Аудит удаления и корзина | FR-DOC-01, SEC-AUD-01 |
| `snapshots.project_version`, `snapshots.invalidated_by/at` | Сравнение со снимком, отметки снимков на «Динамике»; кто пометил «ошибочный» | FR-SNAP-02/03, 10.1 |
| `export_files.snapshot_id`, `status`, `file_name` | Экспорт из снимка; «Готовим файл…»; имя файла | FR-EXP-03, FR-EXP-05 |
| аудиторские поля G-4 у справочников, `project_disciplines`, `threads` | Общее правило 14.2 | 14.2 |

---

## 5. Состояние в Redis (справочно)

PostgreSQL не хранит перечисленное ниже. Владельцы ключей — указанные треки; формат значений фиксируют их задачи.

| Ключ | TTL | Что | Владелец |
|---|---|---|---|
| `session:{id_hash}` | бездействие / абсолютный срок | Активная сессия: user_id, роли, `mfa_passed`, `step_up_until`, CSRF-токен | AUTH-002 |
| `lock:{login}:{ip}` | срок блокировки (15 мин) | Счётчик неудач пары «логин + IP» | AUTH-005 |
| `rl:login:{ip}`, `rl:user:{user_id}:{bucket}` | 1 мин / 1 ч | Rate limit (FR-LOCK-02, SEC-WEB-07) | AUTH-005, SEC |
| `totp:used:{user_id}:{step}` | 120 с | Использованный шаг TOTP (DB-D02) | AUTH-006 |
| `auth:pending:{token_hash}` | 5 мин | Временный токен второго шага входа | AUTH-004 |
| `cell:{project_id}:{node_id}:{field}` | 30 с | Захват ячейки (FR-TREE-31) | RT-005 |
| `presence:{project_id}` | heartbeat | Кто в проекте | RT-006 |
| `portfolio:seen:{session}` | срок сессии | Проекты, открытие которых руководителем пресейла уже записано в аудит за сессию (R-02) | CORE-070 |
| `remind:{project_id}` | 24 ч | «Напомнить не начавшим» не чаще раза в сутки (429) | CORE-053 |

---

## 6. Сводка покрытия 14.2

| № | Таблица 14.2 | Где | Задача | № | Таблица 14.2 | Где | Задача |
|---|---|---|---|---|---|---|---|
| 1 | users | 2.1 | DB-003 | 23 | project_totals_daily | 2.3 | DB-005 (GAP-01) |
| 2 | user_roles | 2.1 | DB-003 | 24 | project_rates | 2.3 | DB-005 |
| 3 | password_history | 2.1 | DB-003 | 25 | project_members | 2.3 | DB-005 |
| 4 | backup_codes | 2.1 | DB-003 | 26 | project_phases | 2.3 | DB-005 |
| 5 | totp_used_codes | Redis (DB-D02) | DB-003 | 27 | project_disciplines | 2.3 | DB-005 |
| 6 | known_devices | 2.1 | DB-003 | 28 | nodes | 2.4 | DB-006 |
| 7 | sessions | 2.1 | DB-003 | 29 | branch_status | 2.3 | DB-005 |
| 8 | system_settings | 2.1 | DB-003 | 30 | node_history | 2.4 | DB-006 |
| 9 | phases | 2.2 | DB-004 | 31 | threads | 2.5 | DB-007 |
| 10 | disciplines | 2.2 | DB-004 | 32 | messages | 2.5 | DB-007 |
| 11 | node_types | 2.2 | DB-004 | 33 | message_history | 2.5 | DB-007 |
| 12 | discipline_profiles | 2.2 | DB-004 | 34 | project_notes | 2.5 | DB-007 |
| 13 | comment_tags | 2.2 | DB-004 | 35 | customer_documents | 2.5 | DB-008 |
| 14 | control_ratios | 2.2 | DB-004 | 36 | support_sessions | 2.3 | DB-005 |
| 15 | app_params | `system_settings` `method.*` (DB-D01) | DB-004 | 37 | message_addressees | 2.5 | DB-007 |
| 16 | work_calendar | 2.2 | DB-004 | 38 | notifications | 2.5 | DB-007 |
| 17 | loss_reasons | 2.2 | DB-004 | 39 | snapshots | 2.6 | DB-008 |
| 18 | vat_rates | 2.2 | DB-004 | 40 | change_log | 2.4 | DB-006 |
| 19 | currencies | 2.2 | DB-004 | 41 | user_view_state | 2.4 | DB-006 |
| 20 | projects | 2.3 | DB-005 | 42 | export_files | 2.6 | DB-008 |
| 21 | project_money | 2.3 | DB-005 | 43 | audit_log | 2.6 (`audit.audit_log`) | DB-009 |
| 22 | project_totals | 2.3 | DB-005 | | | | |

В PLAN.md DB-001 упомянуты «42 таблицы»: это счёт до решения GAP-01; с `project_totals_daily` их 43. Таблица
`project_totals_daily` описана здесь, поэтому отдельный CR в DB, упомянутый в CORE-052, не нужен: до вехи M0
контракт меняется обычным PR (contracts/README.md).

## 7. Перечисления (сводка)

| Тип | Значения | Таблица |
|---|---|---|
| `user_source` | local, ad | users |
| `user_status` | active, blocked, pending_password, anonymized | users |
| `user_block_reason` | manual, ad_disabled, ad_group, ad_missing, not_matched | users |
| `system_role` | superadmin, admin, moderator, presale, presale_head, security_auditor | user_roles |
| `role_source` | manual, ad_group | user_roles |
| `auth_token_kind` | activation, password_reset | auth_tokens |
| `node_type_proposal` | none, proposed, accepted, merged, rejected | node_types |
| `comment_tag_category` | assumption, constraint, risk, tech | comment_tags |
| `project_status` | preparation, estimation, consolidation, completed, archived | projects |
| `project_outcome` | unknown, won, lost, cancelled | projects |
| `quote_figure` | e, p80, p90 | projects |
| `detail_level` | coarse, medium, detailed | projects |
| `project_role` | moderator, expert, presale | project_members |
| `branch_status_value` | not_started, draft, done, not_needed | branch_status |
| `node_kind` | phase, discipline, item | nodes |
| `node_action` | create, update, move, delete, restore, split, collapse, review | node_history |
| `thread_status` | open, resolved | threads |
| `customer_question_status` | new, sent, answered, closed, withdrawn | threads |
| `message_kind` | message, event, customer_answer | messages |
| `message_history_reason` | edit, revoke, edit_after_sent | message_history |
| `addressee_type` | user, discipline, moderators, customer | message_addressees |
| `scan_status` | pending, clean, infected, error | customer_documents |
| `export_status` | pending, ready, failed | export_files |
| `audit_result` | success, failure, denied | audit.audit_log |

Эти же значения — строковые перечисления в `contracts/openapi.yaml` (API-002).
