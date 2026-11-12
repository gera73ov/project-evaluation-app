# Протокол ручной проверки безопасности (SPEC 17.3, QA-022)

Статус: **предварительный прогон команды**. Ниже для каждого пункта чек-листа 17.3 указано, какой
автотест его уже проверяет и что остаётся проверить вручную на stage вместе со службой ИБ.
Протокол считается закрытым, когда служба ИБ проставит результат по каждому пункту и подпишет
его (раздел «Подписи»).

Как читать столбцы:

- **Автотест** — где пункт проверяется в CI или на домашнем test-стенде (e2e-stand, ZAP);
- **Вручную на stage** — что автотест не закрывает: настоящая сеть, настоящий AD, SIEM, глаза
  человека на выгрузке;
- **Результат** — заполняет служба ИБ: «✔», «✘ + номер дефекта» или «н/п».

Автотесты: `backend/tests/...` — pytest (job backend в CI), `e2e/...` — Playwright на test-стенде
(workflow e2e-stand), `backend/tests/integration/ad/...` — на Samba AD (`make test-ad`, QA-012).

| № | Проверка | Автотест | Вручную на stage | Результат |
|---|---|---|---|---|
| CL-01 | Перебор пароля: блок пары «логин + IP» после 5, с другого адреса вход; СА не блокируется, задержка растёт; одинаковое сообщение | `tests/unit/auth/test_lockout.py` (`test_pair_locked_after_five_failures_only_from_that_ip`, `test_superadmin_not_locked_delay_grows_and_alert_after_five`, `test_unknown_login_gets_same_lock`); `tests/integration/auth/test_login_api.py::test_pair_locked_after_failures`, `::test_uniform_failure_and_audit` | 6 неверных паролей с одного ПК, затем вход с другого; текст ошибки одинаковый для неизвестного логина и неверного пароля | |
| CL-02 | Cookie `HttpOnly`, `Secure`, `SameSite=Strict`, `__Host-` | `tests/integration/auth/test_login_api.py::test_login_cookie_attributes` | DevTools → Application → Cookies за Nginx stage | |
| CL-03 | Выход завершает сессию на сервере, старый cookie → 401 | `tests/integration/auth/test_context.py::test_logout_then_old_cookie_is_401`; `test_login_api.py::test_logout_requires_csrf_and_kills_cookie`; `e2e/auth/login.spec.ts` «вход без TOTP и выход» | Повторить запрос со старым cookie (curl) после выхода | |
| CL-04 | Блокировка администратором выкидывает из вкладки ≤ 5 с | `tests/integration/rt/test_two_processes.py` (`session.ended` с `user_blocked` между процессами); `frontend/src/app/SessionWs.test.tsx`; `e2e/admin/admin.spec.ts` «реестр: блокировка модератора…» | Секундомер: администратор блокирует, у пользователя в другом браузере вкладка уходит на вход | |
| CL-05 | Заголовки 12.5 на всех ответах, включая ошибки и статику | `tests/unit/sec/test_web.py`; `test_login_api.py::test_options_and_security_headers` (в том числе 401 и 413); `tests/security/test_csrf.py`; ZAP baseline (QA-021, `deploy/zap/REPORT.md`) | `curl -I` на `/`, `/assets/*.js`, `/api/v1/nonexistent` за Nginx stage | |
| CL-06 | XSS `<img src=x onerror=alert(1)>` выводится текстом: дерево, обсуждение, статистика, письмо, Excel, Word | `e2e/scenarios/roles.spec.ts` (4.5, CL-06 обсуждение, CL-06 статистика; диалогов `alert` нет); `tests/security/test_exports.py::test_every_export_is_escaped_marked_and_audited` | Открыть письмо в почтовом клиенте ИБ; Excel и Word — в настольном Office | |
| CL-07 | IDOR: UUID чужого проекта во всех эндпоинтах → 404 | `tests/security/test_matrix_roles.py::test_foreign_project_is_404`, `::test_matrix_row`; `tests/integration/sec/test_authz_api.py::test_foreign_project_is_404_and_audited` | Выборочно 3–5 эндпоинтов через Burp/ZAP с чужим UUID | |
| CL-08 | Эксперт: нет денег в Network, WS-кадрах, Excel | `tests/security/test_no_money_leak.py` (обход всех GET контракта и WS); `test_exports.py::test_expert_hours_without_money` | DevTools → Network и WS у эксперта на рабочем экране и статистике; поиск «₽» в выгрузке | |
| CL-09 | Суперадминистратор не открывает дерево ни в интерфейсе, ни через API | `tests/integration/adm/test_registry_support_api.py` (CL-09) | Под СА открыть `/projects/{id}` в адресной строке и `GET /api/v1/projects/{id}/tree` | |
| CL-10 | Режим AD: самоподписанный сертификат контроллера → отказ | `tests/integration/ad/test_login_samba.py::test_untrusted_controller_certificate_rejected`; `tests/unit/auth/test_ldap3_directory.py` | Подменить сертификат на тестовом контроллере заказчика (или указать чужой УЦ) и попробовать войти | |
| CL-11 | В логах приложения и Nginx нет паролей, токенов, cookie | `tests/unit/sec/test_logfilter.py` (`test_login_and_reset_scenario_leaves_no_secrets` и др.); `tests/unit/sec/test_nginx_log_format.py` | `grep` по логам stage за день UAT: пароль тестового пользователя, `__Host-session=`, `X-CSRF-Token` | |
| CL-12 | `UPDATE audit.audit_log` ролью приложения → ошибка; `audit verify` проходит; события в SIEM | `tests/integration/db/test_audit_log.py::test_app_role_cannot_modify_audit`; `tests/security/test_audit_chain.py` (nightly); `tests/integration/sec/test_siem.py` | `psql` под ролью приложения; `estimator audit verify` на stage; события в SIEM заказчика | |
| CL-13 | Режим AD: пустой пароль и спецсимволы LDAP не дают входа и не меняют фильтр | `tests/integration/ad/test_login_samba.py::test_empty_password_rejected_without_bind`, `::test_ldap_injection_is_escaped` | Вход с логином `*)(uid=*` и пустым паролем на AD заказчика | |
| CL-14 | CSP: нет нарушений на всех экранах, `style-src` без `'unsafe-inline'`, Mantine через nonce | `e2e/scenarios/roles.spec.ts` (ни одного нарушения CSP за все сценарии ролей); `e2e/work/collab.spec.ts`; `e2e/auth/login.spec.ts`; `tests/unit/sec/test_web.py::test_html_gets_fresh_nonce` | Консоль DevTools на каждом экране под каждой ролью; заголовок CSP за Nginx stage | |
| CL-15 | Документы: EICAR, `.exe` → `.pdf`, `.docm` отклоняются; `Content-Disposition: attachment` | `tests/integration/core/test_documents_api.py::test_infected_and_scan_errors` (EICAR), `::test_type_by_content_and_limits` (`.exe` под видом `.pdf`, макросы в docx/xlsx), `::test_upload_scan_and_download` (`attachment`) | Загрузка EICAR с настоящим ClamAV stage; скачивание — файл сохраняется, а не открывается | |
| CL-16 | Приложение недоступно из интернета; админка СА из сетей вне списка → 404 | `tests/integration/auth/test_admin_networks.py` (вход СА из чужой сети → 404, в том числе с верным паролем) | Внешнее сканирование адреса stage из интернета; вход СА с ПК вне списка сетей | |
| CL-17 | Выгрузки (Excel, Word, CSV аудита) с грифом, ФИО и датой | `tests/security/test_exports.py::test_every_export_is_escaped_marked_and_audited`; `e2e/system/system.spec.ts` (CSV аудита) | Открыть каждую выгрузку и найти гриф, ФИО и дату | |
| CL-18 | Смена SMTP: оповещение ИБ через старый сервер | `tests/integration/sec/test_security_alerts.py::test_smtp_change_alerts_through_old_server_first` | Сменить SMTP на stage и найти письмо в ящике ИБ на старом сервере | |
| CL-19 | Модератор, которому TOTP стал обязателен во время сессии, не видит денег до ввода кода | `tests/acceptance` G-19 (`steps/auth_steps.py::totp_policy_enabled`, деньги → `TOTP_REQUIRED`); `test_login_api.py::test_money_requires_totp_then_step_up`; `e2e/scenarios/roles.spec.ts` G-19 | Включить политику «обязателен» при открытой сессии модератора и обновить блок «Деньги» | |

## Что найдено при подготовке протокола

- CL-02: атрибуты cookie раньше проверялись только частично (имя `__Host-session`). Добавлен
  `test_login_cookie_attributes`: `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, без
  `Domain` и срока; CSRF-cookie без `HttpOnly`, остальные атрибуты те же.
- Остальные пункты уже покрыты автотестами, ссылки в таблице.

## Порядок проверки на stage

1. Команда за день до проверки прогоняет e2e-stand и ZAP на версии stage и прикладывает ссылки
   на зелёные прогоны.
2. Служба ИБ проходит столбец «Вручную на stage» по порядку и заполняет «Результат».
3. По каждому «✘» заводится дефект с номером. Повторная проверка — только этого пункта после
   исправления.

## Подписи

| Роль | ФИО | Дата | Подпись |
|---|---|---|---|
| Служба ИБ | | | |
| Владелец продукта | | | |
| Ответственный от команды | | | |
