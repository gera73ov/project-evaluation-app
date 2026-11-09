/**
 * СГЕНЕРИРОВАНО из contracts/audit-events.yaml командой `npm run api:gen` (FE-065). Не править вручную.
 */
export type AuditCategory = { title: string; visible_to: readonly string[] };
export type AuditEvent = { category: string; title: string };

export const AUDIT_CATEGORIES: Readonly<Record<string, AuditCategory>> = {
  "auth": {
    "title": "Аутентификация",
    "visible_to": [
      "superadmin",
      "security_auditor"
    ]
  },
  "users_roles": {
    "title": "Пользователи и роли",
    "visible_to": [
      "superadmin",
      "security_auditor",
      "admin"
    ]
  },
  "system": {
    "title": "Система",
    "visible_to": [
      "superadmin",
      "security_auditor"
    ]
  },
  "dictionaries": {
    "title": "Справочники",
    "visible_to": [
      "superadmin",
      "security_auditor",
      "admin"
    ]
  },
  "projects": {
    "title": "Проекты",
    "visible_to": [
      "superadmin",
      "security_auditor"
    ]
  },
  "security": {
    "title": "Безопасность",
    "visible_to": [
      "superadmin",
      "security_auditor"
    ]
  },
  "audit": {
    "title": "Аудит",
    "visible_to": [
      "superadmin",
      "security_auditor"
    ]
  }
};

export const AUDIT_EVENTS: Readonly<Record<string, AuditEvent>> = {
  "auth.login.succeeded": {
    "category": "auth",
    "title": "Успешный вход (после пароля и, если нужен, TOTP)"
  },
  "auth.login.failed": {
    "category": "auth",
    "title": "Неуспешный вход"
  },
  "auth.logout": {
    "category": "auth",
    "title": "Выход"
  },
  "auth.session.expired": {
    "category": "auth",
    "title": "Истечение сессии"
  },
  "auth.sessions.terminated": {
    "category": "auth",
    "title": "Завершение сессий пользователем или системой"
  },
  "auth.sessions.revoked_by_ad": {
    "category": "auth",
    "title": "Отзыв сессий проверкой AD (каждые 15 минут и ежедневно)"
  },
  "auth.lockout.pair_locked": {
    "category": "auth",
    "title": "Блокировка пары «логин + IP» по попыткам"
  },
  "auth.lockout.superadmin_delay": {
    "category": "auth",
    "title": "Растущая задержка ответа для IP при неудачах по логину суперадминистратора"
  },
  "auth.step_up.passed": {
    "category": "auth",
    "title": "Пройден step-up (пароль + TOTP) или TOTP для доступа к деньгам"
  },
  "auth.step_up.failed": {
    "category": "auth",
    "title": "Неудачный step-up"
  },
  "auth.password.reset_requested": {
    "category": "auth",
    "title": "Запрос «Забыли пароль» (пишется и для несуществующего логина)"
  },
  "auth.password.set": {
    "category": "auth",
    "title": "Пароль установлен по ссылке активации или сброса"
  },
  "auth.password.changed": {
    "category": "auth",
    "title": "Смена своего пароля в профиле"
  },
  "auth.password.reset_issued": {
    "category": "auth",
    "title": "Администратор, суперадминистратор или консоль выдали ссылку сброса пароля"
  },
  "auth.mfa.enrolled": {
    "category": "auth",
    "title": "Подключение TOTP"
  },
  "auth.mfa.disabled": {
    "category": "auth",
    "title": "Пользователь отключил свой TOTP"
  },
  "auth.mfa.reset": {
    "category": "auth",
    "title": "Сброс TOTP пользователю администратором или суперадминистратором"
  },
  "auth.mfa.backup_codes_regenerated": {
    "category": "auth",
    "title": "Новые резервные коды"
  },
  "users.created": {
    "category": "users_roles",
    "title": "Создание пользователя"
  },
  "users.updated": {
    "category": "users_roles",
    "title": "Изменение ФИО, логина, email (вручную или из AD при входе)"
  },
  "users.blocked": {
    "category": "users_roles",
    "title": "Блокировка пользователя"
  },
  "users.unblocked": {
    "category": "users_roles",
    "title": "Разблокировка пользователя"
  },
  "users.anonymized": {
    "category": "users_roles",
    "title": "Анонимизация пользователя"
  },
  "users.roles.changed": {
    "category": "users_roles",
    "title": "Изменение системных ролей"
  },
  "users.ad_sync.completed": {
    "category": "users_roles",
    "title": "Синхронизация AD (сводка)"
  },
  "users.ad_role_mapping.report": {
    "category": "users_roles",
    "title": "Отчёт при включении сопоставления групп AD с ролями"
  },
  "users.replaced_everywhere": {
    "category": "users_roles",
    "title": "Замена участника во всех проектах (администратор)"
  },
  "system.setup.step_completed": {
    "category": "system",
    "title": "Шаг мастера первичной настройки"
  },
  "system.setup.finished": {
    "category": "system",
    "title": "Мастер первичной настройки завершён"
  },
  "system.auth_mode.switched": {
    "category": "system",
    "title": "Смена способа аутентификации (с отчётом сопоставления)"
  },
  "system.ad_settings.changed": {
    "category": "system",
    "title": "Изменение настроек AD (подключение, группы, сопоставление ролей)"
  },
  "system.settings.changed": {
    "category": "system",
    "title": "Изменение настроек системы (раздел system_settings)"
  },
  "system.privileged_account.changed": {
    "category": "system",
    "title": "Создание, блокировка, разжалование администратора или суперадминистратора; выдача и снятие роли «Аудитор ИБ»"
  },
  "system.cli.executed": {
    "category": "system",
    "title": "Запуск консольной команды estimator"
  },
  "system.audit_chain.verified": {
    "category": "system",
    "title": "Результат проверки цепочки аудита (ежедневно 04:00 и командой)"
  },
  "system.audit.purged": {
    "category": "system",
    "title": "Удалены записи аудита старше срока хранения"
  },
  "system.alert.delivery_failed": {
    "category": "system",
    "title": "Оповещение ИБ не доставлено через старый SMTP"
  },
  "dict.changed": {
    "category": "dictionaries",
    "title": "Любое изменение справочника, «было → стало»"
  },
  "dict.proposed_type.decided": {
    "category": "dictionaries",
    "title": "Решение по предложенному локальному типу"
  },
  "project.created": {
    "category": "projects",
    "title": "Создание проекта (в том числе копированием)"
  },
  "project.status.changed": {
    "category": "projects",
    "title": "Смена статуса проекта, в том числе автоархивация и отмена"
  },
  "project.team.changed": {
    "category": "projects",
    "title": "Изменение команды и ролей в проекте"
  },
  "project.moderator.transferred": {
    "category": "projects",
    "title": "Передача проекта или добавление модератора администратором"
  },
  "project.questions.redirected": {
    "category": "projects",
    "title": "Переадресация открытых вопросов при замене участника"
  },
  "project.opened_by_presale_head": {
    "category": "projects",
    "title": "Первое за сессию открытие чужого проекта руководителем пресейла"
  },
  "project.joined_as_moderator": {
    "category": "projects",
    "title": "Руководитель пресейла стал модератором проекта"
  },
  "project.support_session.opened": {
    "category": "projects",
    "title": "Открытие проекта в режиме поддержки"
  },
  "project.money.changed": {
    "category": "projects",
    "title": "Изменение ставок, валюты, курса, НДС или суммы договора — только факт, без значений"
  },
  "project.snapshot.created": {
    "category": "projects",
    "title": "Снимок оценки"
  },
  "project.snapshot.invalidated": {
    "category": "projects",
    "title": "Пометка снимка «ошибочный»"
  },
  "export.created": {
    "category": "projects",
    "title": "Создание выгрузки (любой вид из contracts/exports.yaml, кроме audit_csv)"
  },
  "export.downloaded": {
    "category": "projects",
    "title": "Скачивание файла выгрузки"
  },
  "project.document.changed": {
    "category": "projects",
    "title": "Загрузка, скачивание, удаление, восстановление документа заказчика"
  },
  "project.purged": {
    "category": "projects",
    "title": "Физическое удаление проекта командой project purge"
  },
  "security.access_denied": {
    "category": "security",
    "title": "Отказ в доступе 403/404 на объекты проекта (не чаще 1 записи в минуту на пользователя и объект)"
  },
  "security.network_denied": {
    "category": "security",
    "title": "Отказ по сетевому ограничению админки суперадминистратора"
  },
  "security.rate_limited": {
    "category": "security",
    "title": "Превышение ограничения частоты"
  },
  "security.file_infected": {
    "category": "security",
    "title": "Заражённый или непроверенный файл документа заказчика"
  },
  "security.superadmin_login_failures": {
    "category": "security",
    "title": "5 неудачных входов подряд по логину суперадминистратора"
  },
  "security.login_failures_burst": {
    "category": "security",
    "title": "Больше 20 неудачных входов за час по одному логину с разных адресов"
  },
  "audit.viewed": {
    "category": "audit",
    "title": "Просмотр журнала аудита (фильтры)"
  },
  "audit.exported": {
    "category": "audit",
    "title": "Выгрузка журнала аудита в CSV"
  }
};
