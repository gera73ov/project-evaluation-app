# DEC-20261110-core-outcome-journal

- **Тип:** решение (DEC), уровень A1
- **Время:** 2026-11-10T16:50:00Z
- **Трек:** CORE (CORE-029, CORE-032); потребители — FE-016 (вкладка «Результат пресейла»),
  FE-015 (вкладка «Журнал проекта»), CORE-070 (сводка по портфелю), CORE-028 (запись «Система»)
- **Основание:** SPEC BR-PRJ-05, Q-14, 3.3, 3.4 (M3.4-11), 11.6 №1, 12.7, 15.2; contracts/openapi.yaml
  (`getOutcome`, `putOutcome`, `getJournal`, `ProjectOutcomePut`, `JournalEntry`), permissions.yaml
  (`outcome.write`, `money.write`, `journal.read`), contracts/db/schema.md 3 (`project_journal`)

## Решение

1. **Сумма договора — как в SPEC (CR-015).** Сначала (PR #96) сделано по контракту: только
   `money.write` и TOTP, то есть модератор проекта до «Завершена». Владелец продукта 10.11.2026
   выбрал BR-PRJ-05: `contract_amount` передаёт тот, у кого есть `outcome.write` и `money.read` с
   TOTP (модератор, пресейл проекта, руководитель пресейла), в любом статусе. Без `money.read` —
   403 `FORBIDDEN`, без TOTP — 403 `TOTP_REQUIRED`. Поле не передано — право на деньги не
   проверяется.
2. **Сумма только при «выигран».** Непустая сумма при другом результате — 422. Смена результата
   сумму не очищает: её меняет и очищает тот, у кого есть право на деньги (иначе пресейл, ошибочно
   выбрав «проигран», стёр бы сумму, которую не может вернуть). Сводка по портфелю берёт сумму
   только у выигранных.
3. **Причина и текст** хранятся только у «проигран» (CHECK `loss_reason`); при другом результате
   очищаются. Выключенная администратором причина допустима, если она уже стоит у проекта. Текст
   хранится только у причины «Другое» (обрезка пробелов, пустой — 422, > 500 — 422).
4. **Журнал.** Результат — запись `outcome.changed` с `outcome`, `loss_reason` (название, а не id:
   справочник меняется) и `loss_reason_text`; сумма — отдельная запись `project.money.changed` с
   `is_money` (CHECK `money_keys` не даёт держать денежный ключ в общей записи). Аудит суммы —
   `project.money.changed` с `fields: [contract_amount]`, без значения.
5. **События.** Изменение результата поднимает версию проекта и шлёт `project.updated` с
   `changes.outcome/loss_reason_id/loss_reason_text` всем, кто видит проект; сумма —
   `money.updated` с `contract_amount` и `totals` в `:money`, кэш итогов пересчитывается.
6. **Чтение журнала.** Новые сверху, курсор по `id` (UUID v7). Записи `is_money` без `money.read`
   (с TOTP) не отдаются вовсе. В денежной записи «было → стало» лежит в `money.changes`, а `changes`
   пустой — так вкладка рисует их денежным цветом (как в моке FE-015).
7. **Имена видов в API.** Таблица только для INSERT, поэтому ранние имена переводятся при чтении:
   `project.team` → `team.changed`, `project.branch_profile` → `branch.profile`,
   `project.money.changed` → `money.changed`. `project.created`, `project.settings`,
   `project.status`, `outcome.changed` — как есть. `project.disciplines` (добавление и удаление
   дисциплины, ключ `disciplines`) и `project.node_type` (новый локальный тип, ключи `name`, `icon`)
   отдаются как записаны: подписи для них — на стороне FE.
