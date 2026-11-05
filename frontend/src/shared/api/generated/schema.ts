/**
 * СГЕНЕРИРОВАНО из contracts/openapi.yaml командой `npm run api:gen` (API-006). Не править вручную:
 * CI сверяет файл с контрактом (`npm run api:gen:check`).
 */
import type { DecimalString } from '../decimal';

export type paths = {
    "/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Вход по логину и паролю */
        post: operations["login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/totp": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Второй шаг входа: код TOTP или резервный код */
        post: operations["loginTotp"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Выход */
        post: operations["logout"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/totp/enroll": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Принудительное подключение TOTP: QR и секрет */
        post: operations["totpEnrollStart"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/totp/enroll/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Подтверждение первым кодом, выдача резервных кодов */
        post: operations["totpEnrollConfirm"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/step-up": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Step-up: пароль и TOTP или только TOTP для денег */
        post: operations["stepUp"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/activate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Установка пароля по ссылке активации */
        post: operations["activate"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/password/forgot": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** «Забыли пароль»: ответ всегда одинаковый */
        post: operations["passwordForgot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/password/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Сброс пароля по ссылке */
        post: operations["passwordReset"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Профиль текущего пользователя */
        get: operations["getMe"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Изменить ФИО (только local) и часовой пояс */
        patch: operations["patchMe"];
        trace?: never;
    };
    "/me/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Активные сессии */
        get: operations["listMySessions"];
        put?: never;
        post?: never;
        /** Завершить сессии, кроме текущей */
        delete: operations["deleteMySessions"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Смена пароля (local) */
        post: operations["changePassword"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/totp": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Подключить TOTP по желанию (шаг 1 — QR; шаг 2 — код) */
        post: operations["enableTotp"];
        /** Отключить TOTP (если не обязателен) */
        delete: operations["disableTotp"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/backup-codes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Новые резервные коды */
        post: operations["regenerateBackupCodes"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/notification-settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Настройки писем */
        get: operations["getNotificationSettings"];
        /** Изменить настройки писем */
        put: operations["putNotificationSettings"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/view-state/{project_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Состояние вида проекта */
        get: operations["getViewState"];
        /** Сохранить состояние вида */
        put: operations["putViewState"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/setup/{step}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Шаг мастера первичной настройки */
        get: operations["getSetupStep"];
        put?: never;
        /** Сохранить шаг мастера */
        post: operations["postSetupStep"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Состояние системы */
        get: operations["getHealth"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/settings/{section}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Раздел настроек
         * @description section: app, smtp, auth, security, siem, retention, digest. Ключи — contracts/settings.schema.json (ADM-000)
         */
        get: operations["getSettings"];
        /**
         * Изменить раздел настроек
         * @description Раздел auth требует system.auth.manage, остальные — system.settings.write
         */
        put: operations["putSettings"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/auth/ad/test-connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Проверить подключение к AD */
        post: operations["adTestConnection"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/auth/ad/test-login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Проверить вход в AD */
        post: operations["adTestLogin"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/auth/switch-mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Переход «Приложение → AD» (dry_run — отчёт) */
        post: operations["switchMode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/auth/switch-mode/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Решения по неоднозначным совпадениям */
        post: operations["switchModeResolve"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/admins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Администраторы, суперадминистраторы, аудиторы ИБ */
        get: operations["listAdmins"];
        put?: never;
        /** Создать администратора, суперадминистратора или аудитора */
        post: operations["createAdmin"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/admins/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Разжаловать */
        delete: operations["demoteAdmin"];
        options?: never;
        head?: never;
        /** Изменить роли или заблокировать */
        patch: operations["patchAdmin"];
        trace?: never;
    };
    "/system/users/{id}/reset-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Сброс пароля администратору или суперадминистратору */
        post: operations["systemResetPassword"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/users/{id}/reset-totp": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Сброс TOTP администратору или суперадминистратору */
        post: operations["systemResetTotp"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/users/{id}/anonymize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Анонимизация заблокированного пользователя */
        post: operations["anonymizeUser"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Реестр проектов без денег */
        get: operations["systemRegistry"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Журнал аудита
         * @description Администратор видит только категории «Справочники» и «Пользователи и роли». Для администратора путь не ограничен сетью FR-SA-06
         */
        get: operations["listAudit"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/system/audit/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Выгрузка журнала аудита в CSV */
        post: operations["exportAudit"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Пользователи */
        get: operations["listUsers"];
        put?: never;
        /** Создать пользователя (режим «Приложение») или завести из AD */
        post: operations["createUser"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Пользователь */
        get: operations["getUser"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Изменить пользователя и системные роли */
        patch: operations["patchUser"];
        trace?: never;
    };
    "/admin/users/{id}/reset-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Ссылка сброса пароля */
        post: operations["adminResetPassword"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users/{id}/reset-totp": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Сброс TOTP */
        post: operations["adminResetTotp"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users/{id}/block": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Заблокировать */
        post: operations["blockUser"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users/{id}/unblock": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Разблокировать */
        post: operations["unblockUser"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/users/{id}/replace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Заменить участника во всех проектах (dry_run — отчёт) */
        post: operations["replaceEverywhere"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/ad/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Поиск в каталоге AD (от 3 символов, до 50 записей) */
        get: operations["adSearch"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/phases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Фазы: список */
        get: operations["listPhases"];
        put?: never;
        /** Фазы: создать */
        post: operations["createPhases"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/phases/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Фазы: удалить, если не используется */
        delete: operations["deletePhases"];
        options?: never;
        head?: never;
        /** Фазы: изменить */
        patch: operations["updatePhases"];
        trace?: never;
    };
    "/admin/disciplines": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Дисциплины: список */
        get: operations["listDisciplines"];
        put?: never;
        /** Дисциплины: создать */
        post: operations["createDisciplines"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/disciplines/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Дисциплины: удалить, если не используется */
        delete: operations["deleteDisciplines"];
        options?: never;
        head?: never;
        /** Дисциплины: изменить */
        patch: operations["updateDisciplines"];
        trace?: never;
    };
    "/admin/node-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Типы узлов: список */
        get: operations["listNodeTypes"];
        put?: never;
        /** Типы узлов: создать */
        post: operations["createNodeTypes"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/node-types/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Типы узлов: удалить, если не используется */
        delete: operations["deleteNodeTypes"];
        options?: never;
        head?: never;
        /** Типы узлов: изменить */
        patch: operations["updateNodeTypes"];
        trace?: never;
    };
    "/admin/profiles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Профили дисциплин: список */
        get: operations["listProfiles"];
        put?: never;
        /** Профили дисциплин: создать */
        post: operations["createProfiles"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/profiles/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Профили дисциплин: удалить, если не используется */
        delete: operations["deleteProfiles"];
        options?: never;
        head?: never;
        /** Профили дисциплин: изменить */
        patch: operations["updateProfiles"];
        trace?: never;
    };
    "/admin/ratios": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Контрольные соотношения: список */
        get: operations["listRatios"];
        put?: never;
        /** Контрольные соотношения: создать */
        post: operations["createRatios"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/ratios/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Контрольные соотношения: удалить, если не используется */
        delete: operations["deleteRatios"];
        options?: never;
        head?: never;
        /** Контрольные соотношения: изменить */
        patch: operations["updateRatios"];
        trace?: never;
    };
    "/admin/tags": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Метки комментариев: список */
        get: operations["listTags"];
        put?: never;
        /** Метки комментариев: создать */
        post: operations["createTags"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/tags/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Метки комментариев: удалить, если не используется */
        delete: operations["deleteTags"];
        options?: never;
        head?: never;
        /** Метки комментариев: изменить */
        patch: operations["updateTags"];
        trace?: never;
    };
    "/admin/currencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Валюты: список */
        get: operations["listCurrencies"];
        put?: never;
        /** Валюты: создать */
        post: operations["createCurrencies"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/currencies/{code}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Валюты: удалить, если не используется */
        delete: operations["deleteCurrencies"];
        options?: never;
        head?: never;
        /** Валюты: изменить */
        patch: operations["updateCurrencies"];
        trace?: never;
    };
    "/admin/vat-rates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ставки НДС: список */
        get: operations["listVatRates"];
        put?: never;
        /** Ставки НДС: создать */
        post: operations["createVatRates"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/vat-rates/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Ставки НДС: удалить, если не используется */
        delete: operations["deleteVatRates"];
        options?: never;
        head?: never;
        /** Ставки НДС: изменить */
        patch: operations["updateVatRates"];
        trace?: never;
    };
    "/admin/loss-reasons": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Причины проигрыша: список */
        get: operations["listLossReasons"];
        put?: never;
        /** Причины проигрыша: создать */
        post: operations["createLossReasons"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/loss-reasons/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Причины проигрыша: удалить, если не используется */
        delete: operations["deleteLossReasons"];
        options?: never;
        head?: never;
        /** Причины проигрыша: изменить */
        patch: operations["updateLossReasons"];
        trace?: never;
    };
    "/admin/calendar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Производственный календарь: годы */
        get: operations["listCalendar"];
        put?: never;
        /** Загрузить CSV data.gov.ru (dry_run — предпросмотр по месяцам) */
        post: operations["uploadCalendar"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/calendar/{year}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Точечные правки года */
        put: operations["putCalendarYear"];
        post?: never;
        /** Удалить календарь года (будет Пн–Пт) */
        delete: operations["deleteCalendarYear"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/proposed-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Предложенные типы */
        get: operations["listProposedTypes"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/proposed-types/{id}/accept": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Добавить в словарь */
        post: operations["acceptProposedType"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/proposed-types/{id}/merge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Объединить с существующим (узлы перепривязываются) */
        post: operations["mergeProposedType"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/proposed-types/{id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Отклонить */
        post: operations["rejectProposedType"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Реестр проектов без денег; фильтр without_moderator */
        get: operations["adminRegistry"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/projects/{id}/moderators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Передать проект / добавить модератора */
        post: operations["transferModerators"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/projects/{id}/support-session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Открыть проект в режиме поддержки (60 минут) */
        post: operations["openSupportSession"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/portfolio/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Реестр всех проектов с деньгами */
        get: operations["portfolioProjects"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/portfolio/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Сводка по портфелю за период */
        get: operations["portfolioSummary"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/portfolio/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Выгрузка сводки в Excel */
        post: operations["portfolioExport"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/join-as-moderator": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Стать модератором проекта (только себя) */
        post: operations["joinAsModerator"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** «Мои оценки» */
        get: operations["listProjects"];
        put?: never;
        /** Создать проект */
        post: operations["createProject"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Настройки проекта (без денег) */
        get: operations["getProject"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Изменить настройки */
        patch: operations["patchProject"];
        trace?: never;
    };
    "/projects/{id}/copy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Копировать проект */
        post: operations["copyProject"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Смена статуса */
        post: operations["changeProjectStatus"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Команда */
        get: operations["getMembers"];
        /** Изменить команду */
        put: operations["putMembers"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/disciplines": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Добавить дисциплину (ветки во всех фазах) */
        post: operations["addDiscipline"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/disciplines/{discipline_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Удалить дисциплину из проекта (все ветки пустые) */
        delete: operations["removeDiscipline"];
        options?: never;
        head?: never;
        /** Профиль ветки на проекте */
        patch: operations["patchDisciplineProfile"];
        trace?: never;
    };
    "/projects/{id}/ad-search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Поиск в AD из команды проекта */
        get: operations["projectAdSearch"];
        put?: never;
        /**
         * Завести учётку «Пользователь» из AD и назначить в проект
         * @description Дополнение к строке 15.2 «GET /projects/{id}/ad-search … и заведение учётки»: заведение — POST того же пути
         */
        post: operations["projectAdCreate"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/members/{user_id}/replace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Заменить заблокированного участника */
        post: operations["replaceMember"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/node-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Локальный тип узла */
        post: operations["createLocalNodeType"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/remind": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** «Напомнить не начавшим» */
        post: operations["remindNotStarted"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/money": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ставки, валюта, курс, НДС и итоги в деньгах */
        get: operations["getMoney"];
        /** Изменить ставки, валюту, курс, НДС */
        put: operations["putMoney"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/outcome": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Результат пресейла */
        get: operations["getOutcome"];
        /** Изменить результат пресейла */
        put: operations["putOutcome"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Документы заказчика */
        get: operations["listDocuments"];
        put?: never;
        /** Загрузить документ (PDF, DOCX, XLSX до 50 МБ) */
        post: operations["uploadDocument"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Скачать документ */
        get: operations["downloadDocument"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Документ в корзину */
        delete: operations["deleteDocument"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/documents/{id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Восстановить документ из корзины */
        post: operations["restoreDocument"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/journal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Журнал проекта */
        get: operations["getJournal"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/members/suggest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Автодополнение адресатов @ */
        get: operations["suggestAddressees"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Закрытые заметки */
        get: operations["listNotes"];
        put?: never;
        /** Написать заметку */
        post: operations["createNote"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notes/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Изменить заметку */
        patch: operations["patchNote"];
        trace?: never;
    };
    "/projects/{id}/tree": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Дерево целиком и версия проекта */
        get: operations["getTree"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/changes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Изменения с версии */
        get: operations["getChanges"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/nodes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Создать узел */
        post: operations["createNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Удалить узел в корзину */
        delete: operations["deleteNode"];
        options?: never;
        head?: never;
        /** Изменить поля узла */
        patch: operations["patchNode"];
        trace?: never;
    };
    "/nodes/{id}/move": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Перенести или изменить порядок */
        post: operations["moveNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/split": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Разбить лист */
        post: operations["splitNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/collapse": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Предложение O/R/P для «Свернуть в лист»
         * @description Дополнение к 15.2: подсказка сумм детей до подтверждения
         */
        get: operations["collapseSuggestion"];
        put?: never;
        /** Свернуть в лист (дети — в корзину одним пакетом) */
        post: operations["collapseNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Поставить или снять «Проверено» */
        post: operations["reviewNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/duplicate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Дублировать узел */
        post: operations["duplicateNode"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/copy-from": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Копировать ветку из другого проекта */
        post: operations["copyBranchFrom"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/trash": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Корзина */
        get: operations["getTrash"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/trash/{batch_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Восстановить пакет из корзины */
        post: operations["restoreTrash"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** История узла */
        get: operations["getNodeHistory"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/branches/{phase}/{discipline}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Статус ветки */
        put: operations["putBranchStatus"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Вопросы и обсуждения проекта */
        get: operations["listThreads"];
        put?: never;
        /** Задать вопрос (в т. ч. @заказчик) */
        post: operations["createThread"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/nodes/{id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Лента узла */
        get: operations["listNodeMessages"];
        put?: never;
        /** Сообщение в ленту узла */
        post: operations["postNodeMessage"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Ответ в вопрос */
        post: operations["replyThread"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/messages/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Править своё сообщение */
        patch: operations["editMessage"];
        trace?: never;
    };
    "/messages/{id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Отозвать сообщение */
        post: operations["revokeMessage"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** «Решено» */
        post: operations["resolveThread"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/reopen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Переоткрыть */
        post: operations["reopenThread"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/customer-questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Вопросы заказчику */
        get: operations["listCustomerQuestions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/customer-questions/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Выгрузить в Excel или Word (новые → отправлен) */
        post: operations["exportCustomerQuestions"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/answer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Внести ответ заказчика */
        post: operations["answerCustomerQuestion"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/withdraw": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Снять вопрос */
        post: operations["withdrawCustomerQuestion"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/threads/{id}/question": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Правка текста вопроса заказчику */
        patch: operations["editCustomerQuestion"];
        trace?: never;
    };
    "/projects/{id}/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Статистика */
        get: operations["getStats"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/stats/{tab}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Excel таблиц вкладки статистики */
        get: operations["exportStatsTab"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/assumptions/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Word «Допущения и риски» */
        get: operations["exportAssumptions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Снимки */
        get: operations["listSnapshots"];
        put?: never;
        /** Сделать снимок */
        post: operations["createSnapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/snapshots/{id}/invalidate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Пометить «ошибочный» */
        post: operations["invalidateSnapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/snapshots/{id}/diff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Сравнение со снимком или двух снимков */
        get: operations["diffSnapshot"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/snapshots/{id}/diff/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Экспорт сравнения в Excel */
        post: operations["exportDiff"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/projects/{id}/exports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Экспорт «Часы» или «С деньгами»
         * @description kind = money_xlsx требует export.money и TOTP
         */
        post: operations["createExport"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exports/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Статус выгрузки
         * @description Файл доступен только запросившему пользователю
         */
        get: operations["getExport"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exports/{id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Скачать файл выгрузки
         * @description Дополнение к 15.2: ссылка download_url из GET /exports/{id}
         */
        get: operations["downloadExport"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Уведомления «Мне» */
        get: operations["listNotifications"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notifications/read": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Отметить прочитанными */
        post: operations["markNotificationsRead"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/ws": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * WebSocket-канал событий (Upgrade)
         * @description Протокол — contracts/ws-events.schema.json (RT-001). Проверка Origin; команда subscribe проверяет tree.read
         */
        get: operations["websocket"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
};
export type webhooks = Record<string, never>;
export type components = {
    schemas: {
        /**
         * Format: uuid
         * @description UUID v7 (api-conventions 2.3)
         */
        Uuid: string;
        /** @description Десятичное число строкой (api-conventions 2.1); на вход сервер принимает и запятую */
        DecimalString: DecimalString;
        /** @description Расчётные часы: 2 знака, ROUND_HALF_UP (15.3) */
        HoursString: DecimalString;
        /** @description Деньги: целое число ₽ или единиц валюты КП (BR-MONEY-04) */
        MoneyString: DecimalString;
        /** @description O/R/P на вход: 0–99 999,5, округляется до 0,5 (BR-CALC-03); null — очистить */
        HoursInput: string | null;
        /**
         * Format: date-time
         * @description ISO 8601 UTC с Z
         */
        Timestamp: string;
        /** Format: date */
        Date: string;
        /** @description RFC 9457 (api-conventions 5); расширения — по коду в errors.yaml */
        Problem: {
            /** Format: uri */
            type: string;
            title: string;
            status: number;
            /** @description Код из contracts/errors.yaml */
            code: string;
            detail?: string;
            error_id: string;
            instance?: string;
        };
        UserRef: {
            id: components["schemas"]["Uuid"];
            full_name: string;
            initials?: string;
            is_active?: boolean;
        };
        /** @enum {string} */
        SystemRole: "superadmin" | "admin" | "moderator" | "presale" | "presale_head" | "security_auditor";
        /** @enum {string} */
        ProjectRole: "moderator" | "expert" | "presale";
        /** @enum {string} */
        ProjectStatus: "preparation" | "estimation" | "consolidation" | "completed" | "archived";
        /** @enum {string} */
        BranchStatusValue: "not_started" | "draft" | "done" | "not_needed";
        /** @enum {string} */
        QuoteFigure: "e" | "p80" | "p90";
        /** @enum {string} */
        DetailLevel: "coarse" | "medium" | "detailed";
        /** @enum {string} */
        Outcome: "unknown" | "won" | "lost" | "cancelled";
        /** @enum {string} */
        CustomerStatus: "new" | "sent" | "answered" | "closed" | "withdrawn";
        /** @description Часы без денег */
        HoursTotals: {
            e: components["schemas"]["HoursString"];
            sigma?: components["schemas"]["HoursString"];
            p80: components["schemas"]["HoursString"];
            p90: components["schemas"]["HoursString"];
        };
        LoginRequest: {
            login: string;
            /** Format: password */
            password: string;
        };
        /** @description step=done — сессия создана (Set-Cookie); totp — нужен код; enroll — сессия до подключения TOTP (FR-2FA-04) */
        LoginResponse: {
            /** @enum {string} */
            step: "done" | "totp" | "enroll";
            /** @description Временный токен шага TOTP, 5 минут; только при step = totp */
            login_token?: string;
            expires_in?: number;
        };
        /** @description Ровно одно из code / backup_code */
        TotpLoginRequest: {
            login_token: string;
            code?: string;
            backup_code?: string;
        };
        TotpEnrollStart: {
            otpauth_uri: string;
            /** @description Base32 для ручного ввода */
            secret: string;
        };
        TotpCode: {
            code: string;
        };
        BackupCodes: {
            backup_codes: string[];
        };
        /** @description totp_only=true — подтверждение кодом для денег (FR-2FA-05), пароль не нужен */
        StepUpRequest: {
            /** Format: password */
            password?: string;
            code: string;
            /** @default false */
            totp_only: boolean;
        };
        StepUpResponse: {
            mfa_passed: boolean;
            step_up_until: components["schemas"]["Timestamp"] | null;
        };
        TokenPassword: {
            token: string;
            /** Format: password */
            password: string;
        };
        ForgotRequest: {
            login_or_email: string;
        };
        Me: {
            id: components["schemas"]["Uuid"];
            login: string;
            full_name: string;
            email: string | null;
            /** @enum {string} */
            source: "local" | "ad";
            timezone: string | null;
            system_roles: components["schemas"]["SystemRole"][];
            totp_enabled: boolean;
            totp_required: boolean;
            mfa_passed: boolean;
            /** @enum {string} */
            auth_mode: "app" | "ad";
            session_expires_at: components["schemas"]["Timestamp"];
            idle_timeout_seconds: number;
        };
        MePatch: {
            /** @description Только local */
            full_name?: string;
            timezone?: string | null;
        };
        Session: {
            /** @description Непрозрачный id (хэш) */
            id: string;
            current: boolean;
            user_agent: string | null;
            ip: string;
            created_at: components["schemas"]["Timestamp"];
            last_seen_at: components["schemas"]["Timestamp"];
        };
        PasswordChange: {
            /** Format: password */
            current_password: string;
            /** Format: password */
            new_password: string;
        };
        NotificationSettings: {
            notify_digest: boolean;
            notify_questions: boolean;
        };
        ViewState: {
            /** @description Раскрытие, фильтры, ширины (FR-TREE-14), ≤ 64 КБ */
            state: Record<string, never>;
        };
        SetupStep: {
            /** @enum {string} */
            step: "app" | "smtp" | "auth" | "security" | "first_admin";
            done: boolean;
            values?: Record<string, never>;
        };
        SetupStepWrite: {
            /** @description Ключи шага по contracts/settings.schema.json */
            values: Record<string, never>;
            /** @default false */
            complete: boolean;
        };
        Health: {
            app_version: string;
            schema_version: string;
            components: {
                /** @enum {string} */
                name: "db" | "redis" | "smtp" | "ldap" | "siem" | "queue" | "backup" | "audit_chain" | "audit_purge";
                ok: boolean;
                detail: string | null;
                checked_at: components["schemas"]["Timestamp"];
            }[];
        };
        SettingsSection: {
            section: string;
            /** @description Ключи раздела по contracts/settings.schema.json; секреты не отдаются (x-secret), вместо них {"set": true} */
            values: Record<string, never>;
        };
        SettingsWrite: {
            values: Record<string, never>;
        };
        AdTestLogin: {
            login: string;
            /** Format: password */
            password: string;
        };
        AdTestResult: {
            ok: boolean;
            elapsed_ms: number;
            detail?: string | null;
            user?: {
                full_name: string;
                email: string | null;
                disabled: boolean;
                groups: string[];
                roles: components["schemas"]["SystemRole"][];
                in_access_group: boolean;
            } | null;
        };
        SwitchModeRequest: {
            /** @enum {string} */
            mode: "ad" | "local";
            /** @default true */
            dry_run: boolean;
        };
        SwitchCandidate: {
            user_id: components["schemas"]["Uuid"];
            login: string;
            full_name: string;
            ad_candidates: {
                object_guid: components["schemas"]["Uuid"];
                login: string;
                full_name: string;
            }[];
        };
        SwitchReport: {
            matched: components["schemas"]["SwitchCandidate"][];
            ambiguous: components["schemas"]["SwitchCandidate"][];
            not_found: components["schemas"]["SwitchCandidate"][];
            applied: boolean;
        };
        SwitchResolve: {
            /** @description object_guid = null — отклонить сопоставление */
            decisions: {
                user_id: components["schemas"]["Uuid"];
                object_guid: components["schemas"]["Uuid"] | null;
            }[];
        };
        AdminAccount: {
            id: components["schemas"]["Uuid"];
            login: string;
            full_name: string;
            email: string | null;
            roles: ("superadmin" | "admin" | "security_auditor")[];
            /** @enum {string} */
            status: "active" | "blocked" | "pending_password";
            totp_enabled: boolean;
            last_login_at: components["schemas"]["Timestamp"] | null;
        };
        AdminAccountCreate: {
            login: string;
            /** Format: email */
            email: string;
            full_name: string;
            /** @enum {string} */
            role: "superadmin" | "admin" | "security_auditor";
            ad_object_guid?: components["schemas"]["Uuid"] | null;
        };
        AdminAccountPatch: {
            roles?: ("superadmin" | "admin" | "security_auditor")[];
            /** @enum {string} */
            status?: "active" | "blocked";
        };
        ActivationLink: {
            emailed: boolean;
            activation_url: string | null;
            expires_at: components["schemas"]["Timestamp"];
        };
        /** @description Реестр без денег (FR-ADM-06, 7.5) */
        RegistryProject: {
            id: components["schemas"]["Uuid"];
            name: string;
            customer: string;
            moderators: components["schemas"]["UserRef"][];
            status: components["schemas"]["ProjectStatus"];
            created_at: components["schemas"]["Timestamp"];
            updated_at: components["schemas"]["Timestamp"];
            no_moderator_since: components["schemas"]["Timestamp"] | null;
            days_without_moderator: number | null;
        };
        AuditEntry: {
            id: number;
            ts: components["schemas"]["Timestamp"];
            event_type: string;
            category: string;
            /** @enum {string} */
            result: "success" | "failure" | "denied";
            user_id: components["schemas"]["Uuid"] | null;
            login: string | null;
            ip: string | null;
            user_agent: string | null;
            object_type: string | null;
            object_id: string | null;
            details: Record<string, never>;
        };
        AuditExportRequest: {
            from: components["schemas"]["Timestamp"];
            to: components["schemas"]["Timestamp"];
            user_id?: components["schemas"]["Uuid"] | null;
            event_type?: string | null;
            result?: ("success" | "failure" | "denied") | null;
        };
        User: {
            id: components["schemas"]["Uuid"];
            login: string;
            full_name: string;
            email: string | null;
            /** @enum {string} */
            source: "local" | "ad";
            system_roles: {
                role: components["schemas"]["SystemRole"];
                /** @enum {string} */
                source: "manual" | "ad_group";
            }[];
            /** @enum {string} */
            status: "active" | "blocked" | "pending_password" | "anonymized";
            block_reason: ("manual" | "ad_disabled" | "ad_group" | "ad_missing" | "not_matched") | null;
            last_login_at: components["schemas"]["Timestamp"] | null;
            totp_enabled: boolean;
        };
        /** @description Режим «Приложение» — login/email/ФИО; режим AD — ad_object_guid из поиска (FR-AUTH-AD-10) */
        UserCreate: {
            login: string;
            /** Format: email */
            email?: string;
            full_name: string;
            roles: ("moderator" | "presale" | "presale_head")[];
            ad_object_guid?: components["schemas"]["Uuid"] | null;
        };
        UserPatch: {
            full_name?: string;
            email?: string | null;
            roles?: ("moderator" | "presale" | "presale_head")[];
        };
        BlockRequest: {
            reason?: string | null;
        };
        AdSearchItem: {
            object_guid: components["schemas"]["Uuid"];
            login: string;
            full_name: string;
            email: string | null;
            department: string | null;
            in_access_group: boolean;
            user_id: components["schemas"]["Uuid"] | null;
        };
        ReplaceRequest: {
            replacement_user_id: components["schemas"]["Uuid"];
            /** @default true */
            dry_run: boolean;
            /** @description Отмеченные проекты; при dry_run не нужен */
            project_ids?: components["schemas"]["Uuid"][];
        };
        ReplaceReport: {
            projects: {
                project_id: components["schemas"]["Uuid"];
                name: string;
                roles: {
                    role: components["schemas"]["ProjectRole"];
                    discipline_id: components["schemas"]["Uuid"] | null;
                    is_reviewer: boolean;
                }[];
                applicable: boolean;
                problem: ("replacement_lacks_moderator_role" | "replacement_lacks_presale_role") | null;
                open_questions: number;
            }[];
            applied: boolean;
        };
        Phase: {
            id: components["schemas"]["Uuid"];
            name: string;
            sort_order: number;
            is_cross_cutting: boolean;
            is_active: boolean;
        };
        PhaseWrite: {
            name?: string;
            sort_order?: number;
            is_cross_cutting?: boolean;
            is_active?: boolean;
        };
        Discipline: {
            id: components["schemas"]["Uuid"];
            name: string;
            short_name: string;
            color: string;
            default_profile_id: components["schemas"]["Uuid"] | null;
            is_active: boolean;
        };
        DisciplineWrite: {
            name?: string;
            short_name?: string;
            color?: string;
            default_profile_id?: components["schemas"]["Uuid"] | null;
            is_active?: boolean;
        };
        Norm: {
            label: string;
            o: components["schemas"]["DecimalString"];
            r: components["schemas"]["DecimalString"];
            p: components["schemas"]["DecimalString"];
        };
        NodeType: {
            id: components["schemas"]["Uuid"];
            name: string;
            /** @description Ключ из курируемого набора (GAP-07) */
            icon: string;
            norms: components["schemas"]["Norm"][];
            readonly is_system: boolean;
            is_active: boolean;
        };
        NodeTypeWrite: {
            name?: string;
            /** @description Ключ из курируемого набора (GAP-07) */
            icon?: string;
            norms?: components["schemas"]["Norm"][];
            readonly is_system?: boolean;
            is_active?: boolean;
        };
        Profile: {
            id: components["schemas"]["Uuid"];
            discipline_id: components["schemas"]["Uuid"];
            name: string;
            type_chain: components["schemas"]["Uuid"][];
            is_active: boolean;
        };
        ProfileWrite: {
            discipline_id?: components["schemas"]["Uuid"];
            name?: string;
            type_chain?: components["schemas"]["Uuid"][];
            is_active?: boolean;
        };
        Ratio: {
            id: components["schemas"]["Uuid"];
            discipline_a_id: components["schemas"]["Uuid"];
            disciplines_b: components["schemas"]["Uuid"][];
            min_pct: components["schemas"]["DecimalString"];
            max_pct: components["schemas"]["DecimalString"];
            is_active: boolean;
        };
        RatioWrite: {
            discipline_a_id?: components["schemas"]["Uuid"];
            disciplines_b?: components["schemas"]["Uuid"][];
            min_pct?: components["schemas"]["DecimalString"];
            max_pct?: components["schemas"]["DecimalString"];
            is_active?: boolean;
        };
        Tag: {
            id: components["schemas"]["Uuid"];
            name: string;
            short_name: string;
            color: string;
            /** @enum {string} */
            category: "assumption" | "constraint" | "risk" | "tech";
            is_active: boolean;
        };
        TagWrite: {
            name?: string;
            short_name?: string;
            color?: string;
            /** @enum {string} */
            category?: "assumption" | "constraint" | "risk" | "tech";
            is_active?: boolean;
        };
        Currency: {
            code: string;
            symbol: string;
            is_active: boolean;
        };
        CurrencyWrite: {
            code?: string;
            symbol?: string;
            is_active?: boolean;
        };
        VatRate: {
            id: components["schemas"]["Uuid"];
            name: string;
            percent: components["schemas"]["DecimalString"] | null;
            is_default: boolean;
            is_active: boolean;
        };
        VatRateWrite: {
            name?: string;
            percent?: components["schemas"]["DecimalString"] | null;
            is_default?: boolean;
            is_active?: boolean;
        };
        LossReason: {
            id: components["schemas"]["Uuid"];
            name: string;
            is_other: boolean;
            is_active: boolean;
        };
        LossReasonWrite: {
            name?: string;
            is_other?: boolean;
            is_active?: boolean;
        };
        CalendarYear: {
            year: number;
            days: {
                date: components["schemas"]["Date"];
                is_working: boolean;
            }[];
        };
        CalendarPreview: {
            year: number;
            months: {
                month: number;
                working_days: number;
                non_working: components["schemas"]["Date"][];
                working_weekends: components["schemas"]["Date"][];
            }[];
            saved: boolean;
        };
        ProposedType: {
            id: components["schemas"]["Uuid"];
            name: string;
            icon: string;
            project_id: components["schemas"]["Uuid"];
            project_name: string;
            author: components["schemas"]["UserRef"];
            created_at: components["schemas"]["Timestamp"];
            nodes_count: number;
        };
        MergeRequest: {
            target_type_id: components["schemas"]["Uuid"];
        };
        ModeratorsTransfer: {
            add_user_ids?: components["schemas"]["Uuid"][];
            remove_user_ids?: components["schemas"]["Uuid"][];
        };
        SupportSessionCreate: {
            reason: string;
        };
        SupportSession: {
            id: components["schemas"]["Uuid"];
            project_id: components["schemas"]["Uuid"];
            expires_at: components["schemas"]["Timestamp"];
        };
        /** @description Только с money.read и TOTP (FR-HOME-04) */
        ProjectListItemMoney: {
            currency: string;
            quote_cur: components["schemas"]["MoneyString"] | null;
            quote_rub: components["schemas"]["MoneyString"] | null;
            rates_missing: boolean;
        };
        ProjectListItem: {
            id: components["schemas"]["Uuid"];
            name: string;
            customer: string;
            status: components["schemas"]["ProjectStatus"];
            my_roles: {
                role: components["schemas"]["ProjectRole"];
                discipline_id: components["schemas"]["Uuid"] | null;
                is_reviewer: boolean;
            }[];
            my_progress?: {
                done: number;
                total: number;
            } | null;
            deadline: components["schemas"]["Date"] | null;
            deadline_alert: boolean;
            questions_to_me: number;
            updated_at: components["schemas"]["Timestamp"];
            quote_figure: components["schemas"]["QuoteFigure"];
            quote_hours: components["schemas"]["HoursString"] | null;
            money?: components["schemas"]["ProjectListItemMoney"];
        };
        ProjectCreate: {
            name: string;
            customer: string;
            description?: string;
            phase_ids: components["schemas"]["Uuid"][];
            detail_level?: components["schemas"]["DetailLevel"];
            deadline?: components["schemas"]["Date"] | null;
        };
        ProjectPhase: {
            phase_id: components["schemas"]["Uuid"];
            name: string;
            is_cross_cutting: boolean;
            is_enabled: boolean;
            in_pm_base: boolean;
        };
        ProjectDiscipline: {
            discipline_id: components["schemas"]["Uuid"];
            name: string;
            profile_id: components["schemas"]["Uuid"];
            has_expert: boolean;
        };
        /** @description Настройки проекта без денег (11.6: блока «Деньги» нет в ответе) */
        Project: {
            id: components["schemas"]["Uuid"];
            name: string;
            customer: string;
            description: string;
            status: components["schemas"]["ProjectStatus"];
            outcome: components["schemas"]["Outcome"];
            detail_level: components["schemas"]["DetailLevel"];
            pm_percent: components["schemas"]["DecimalString"];
            pm_percent_reason: string;
            quote_figure: components["schemas"]["QuoteFigure"];
            duration_weeks: number | null;
            deadline: components["schemas"]["Date"] | null;
            version: number;
            phases: components["schemas"]["ProjectPhase"][];
            disciplines: components["schemas"]["ProjectDiscipline"][];
            completed_at?: components["schemas"]["Timestamp"] | null;
            archived_at?: components["schemas"]["Timestamp"] | null;
            cancel_reason?: string | null;
            created_at: components["schemas"]["Timestamp"];
            /** @enum {string} */
            access: "member" | "presale_head" | "support";
            /** @description Коды прав пользователя в этом проекте (для интерфейса; сервер проверяет сам) */
            my_permissions: string[];
            support_expires_at?: components["schemas"]["Timestamp"] | null;
        };
        ProjectPatch: {
            name?: string;
            customer?: string;
            description?: string;
            detail_level?: components["schemas"]["DetailLevel"];
            pm_percent?: components["schemas"]["DecimalString"];
            pm_percent_reason?: string;
            quote_figure?: components["schemas"]["QuoteFigure"];
            duration_weeks?: number | null;
            deadline?: components["schemas"]["Date"] | null;
            phases?: {
                phase_id: components["schemas"]["Uuid"];
                is_enabled?: boolean;
                in_pm_base?: boolean;
            }[];
            /** @default false */
            confirm: boolean;
        };
        ProjectVersioned: {
            project: components["schemas"]["Project"];
            project_version: number;
        };
        CopyProject: {
            name?: string;
        };
        StatusChange: {
            to: components["schemas"]["ProjectStatus"];
            /** @description Обязательна для «Оценка → Архив» (FR-PRJ-05) */
            reason?: string;
        };
        StatusChangeResult: {
            status: components["schemas"]["ProjectStatus"];
            project_version: number;
            warnings: {
                /** @enum {string} */
                code: "branches_not_done" | "open_customer_questions" | "no_snapshot" | "disciplines_without_expert";
                count: number;
            }[];
        };
        Member: {
            user: components["schemas"]["UserRef"];
            role: components["schemas"]["ProjectRole"];
            discipline_id: components["schemas"]["Uuid"] | null;
            is_reviewer: boolean;
            /** @enum {string} */
            status: "active" | "blocked" | "pending_password";
            added_by_admin_self: boolean;
        };
        /** @description Полный состав команды (замена списка) */
        MembersPut: {
            members: {
                user_id: components["schemas"]["Uuid"];
                role: components["schemas"]["ProjectRole"];
                discipline_id?: components["schemas"]["Uuid"] | null;
                /** @default false */
                is_reviewer: boolean;
            }[];
        };
        DisciplineAdd: {
            discipline_id: components["schemas"]["Uuid"];
        };
        DisciplineProfilePatch: {
            profile_id: components["schemas"]["Uuid"];
        };
        ProjectAdCreate: {
            object_guid: components["schemas"]["Uuid"];
            discipline_id: components["schemas"]["Uuid"];
            /** @default false */
            is_reviewer: boolean;
        };
        MemberReplace: {
            replacement_user_id: components["schemas"]["Uuid"];
        };
        LocalNodeType: {
            name: string;
            icon: string;
        };
        RemindResult: {
            sent_to: number;
        };
        /** @description discipline_id = null — ставка УП; rate_rub = null — не задана */
        Rate: {
            discipline_id: components["schemas"]["Uuid"] | null;
            rate_rub: components["schemas"]["MoneyString"] | null;
        };
        /** @description Деньги одной цифры по 6.4; null — переполнение или нет НДС */
        MoneyFigure: {
            k: components["schemas"]["DecimalString"] | null;
            rows_rub: {
                discipline_id: components["schemas"]["Uuid"] | null;
                amount: components["schemas"]["MoneyString"];
            }[];
            total_rub: components["schemas"]["MoneyString"] | null;
            vat_rub: components["schemas"]["MoneyString"] | null;
            total_with_vat_rub: components["schemas"]["MoneyString"] | null;
            rows_cur: {
                discipline_id: components["schemas"]["Uuid"] | null;
                amount: components["schemas"]["MoneyString"];
            }[];
            total_cur: components["schemas"]["MoneyString"] | null;
            vat_cur: components["schemas"]["MoneyString"] | null;
            total_with_vat_cur: components["schemas"]["MoneyString"] | null;
        };
        /** @description Деньги проекта (SEC-AUTHZ-04) */
        ProjectMoney: {
            currency: string;
            exchange_rate: components["schemas"]["DecimalString"];
            vat_rate_id: components["schemas"]["Uuid"];
            vat_percent: components["schemas"]["DecimalString"] | null;
            rates: components["schemas"]["Rate"][];
            /** @description id дисциплин или «pm» (BR-MONEY-02) */
            rates_missing: string[];
            figures: {
                e?: components["schemas"]["MoneyFigure"];
                p80?: components["schemas"]["MoneyFigure"];
                p90?: components["schemas"]["MoneyFigure"];
            };
            updated_at: components["schemas"]["Timestamp"];
            project_version: number;
        };
        ProjectMoneyPut: {
            currency?: string;
            exchange_rate?: components["schemas"]["DecimalString"];
            vat_rate_id?: components["schemas"]["Uuid"];
            rates?: {
                discipline_id: components["schemas"]["Uuid"] | null;
                rate_rub: string | null;
            }[];
        };
        OutcomeMoney: {
            contract_amount: components["schemas"]["MoneyString"] | null;
        };
        ProjectOutcome: {
            outcome: components["schemas"]["Outcome"];
            loss_reason_id: components["schemas"]["Uuid"] | null;
            loss_reason_text: string | null;
            money?: components["schemas"]["OutcomeMoney"];
        };
        /** @description contract_amount — только с money.write и TOTP */
        ProjectOutcomePut: {
            outcome: components["schemas"]["Outcome"];
            loss_reason_id?: components["schemas"]["Uuid"] | null;
            loss_reason_text?: string | null;
            contract_amount?: components["schemas"]["MoneyString"] | null;
        };
        Document: {
            id: components["schemas"]["Uuid"];
            file_name: string;
            mime: string;
            size_bytes: number;
            /** @enum {string} */
            scan_status: "pending" | "clean" | "infected" | "error";
            uploaded_by: components["schemas"]["UserRef"];
            uploaded_at: components["schemas"]["Timestamp"];
            deleted_at: components["schemas"]["Timestamp"] | null;
        };
        DocumentList: {
            items: components["schemas"]["Document"][];
            used_bytes: number;
            limit_bytes: number;
        };
        JournalEntryMoney: {
            changes: Record<string, never>;
        };
        /** @description Записи об изменении денег приходят только с money.read: у остальных их нет в списке */
        JournalEntry: {
            id: components["schemas"]["Uuid"];
            created_at: components["schemas"]["Timestamp"];
            user: components["schemas"]["UserRef"] | null;
            action: string;
            /** @description {поле: [было, стало]} */
            changes: Record<string, never>;
            money?: components["schemas"]["JournalEntryMoney"];
        };
        SuggestItem: {
            /** @enum {string} */
            target_type: "user" | "discipline" | "moderators" | "customer";
            target_id: components["schemas"]["Uuid"] | null;
            label: string;
        };
        Note: {
            id: components["schemas"]["Uuid"];
            node_id: components["schemas"]["Uuid"] | null;
            author: components["schemas"]["UserRef"];
            body: string;
            created_at: components["schemas"]["Timestamp"];
            edited_at: components["schemas"]["Timestamp"] | null;
        };
        NoteCreate: {
            node_id?: components["schemas"]["Uuid"] | null;
            body: string;
        };
        NotePatch: {
            body: string;
        };
        CommentLine: {
            tag_id: components["schemas"]["Uuid"] | null;
            text: string;
        };
        /** @description Узел без денег (SEC-AUTHZ-04). Расчётные поля — по SPEC 6 (ARCH-03) */
        Node: {
            id: components["schemas"]["Uuid"];
            parent_id: components["schemas"]["Uuid"] | null;
            /** @enum {string} */
            kind: "phase" | "discipline" | "item";
            phase_id: components["schemas"]["Uuid"];
            discipline_id: components["schemas"]["Uuid"] | null;
            type_id: components["schemas"]["Uuid"] | null;
            title: string;
            position: string;
            o: components["schemas"]["DecimalString"] | null;
            r: components["schemas"]["DecimalString"] | null;
            p: components["schemas"]["DecimalString"] | null;
            multiplier: number;
            comment_lines: components["schemas"]["CommentLine"][] | null;
            reviewed_by?: components["schemas"]["UserRef"] | null;
            reviewed_at?: components["schemas"]["Timestamp"] | null;
            self_review?: boolean;
            version: number;
            field_versions?: Record<string, never>;
            e: components["schemas"]["HoursString"] | null;
            sigma: components["schemas"]["HoursString"] | null;
            p80?: components["schemas"]["HoursString"] | null;
            p90?: components["schemas"]["HoursString"] | null;
            sum_o?: components["schemas"]["HoursString"] | null;
            sum_r?: components["schemas"]["HoursString"] | null;
            sum_p?: components["schemas"]["HoursString"] | null;
            leaf_state?: ("valid" | "zero" | "empty" | "invalid") | null;
            is_large?: boolean;
            is_repeating?: boolean;
            unaccounted_leaves?: number;
            messages_count?: number;
            open_questions?: number;
            questions_to_me?: number;
        };
        BranchStatus: {
            phase_id: components["schemas"]["Uuid"];
            discipline_id: components["schemas"]["Uuid"];
            status: components["schemas"]["BranchStatusValue"];
            changed_by: components["schemas"]["UserRef"] | null;
            changed_at: components["schemas"]["Timestamp"];
            open_questions: number;
            has_expert: boolean;
        };
        Tree: {
            project_version: number;
            nodes: components["schemas"]["Node"][];
            branch_statuses: components["schemas"]["BranchStatus"][];
            totals: components["schemas"]["TreeTotals"];
        };
        TreeTotals: {
            works: components["schemas"]["HoursTotals"];
            pm: components["schemas"]["HoursTotals"];
            total: components["schemas"]["HoursTotals"];
            unaccounted_leaves: number;
            nodes_count: number;
            /** @constant */
            nodes_limit: 5000;
        };
        NodeCreate: {
            parent_id: components["schemas"]["Uuid"];
            after_id?: components["schemas"]["Uuid"] | null;
            type_id?: components["schemas"]["Uuid"] | null;
            title: string;
            o?: components["schemas"]["HoursInput"];
            r?: components["schemas"]["HoursInput"];
            p?: components["schemas"]["HoursInput"];
            multiplier?: number;
        };
        NodeChanges: {
            title?: string;
            type_id?: components["schemas"]["Uuid"] | null;
            o?: components["schemas"]["HoursInput"];
            r?: components["schemas"]["HoursInput"];
            p?: components["schemas"]["HoursInput"];
            multiplier?: number;
            comment_lines?: components["schemas"]["CommentLine"][] | null;
        };
        NodePatch: {
            base_version: number;
            changes: components["schemas"]["NodeChanges"];
        };
        AncestorTotals: {
            id: components["schemas"]["Uuid"];
            e: components["schemas"]["HoursString"];
            sigma: components["schemas"]["HoursString"];
        };
        BranchStatusChange: {
            phase_id: components["schemas"]["Uuid"];
            discipline_id: components["schemas"]["Uuid"];
            status: components["schemas"]["BranchStatusValue"];
            was: components["schemas"]["BranchStatusValue"];
        };
        /** @description Ответ правки узла (15.3). Денег нет никогда */
        NodeMutation: {
            node: components["schemas"]["Node"];
            project_version: number;
            ancestors: components["schemas"]["AncestorTotals"][];
            totals: components["schemas"]["HoursTotals"];
            branch_status: components["schemas"]["BranchStatusChange"] | null;
            /** @description Поля, округлённые до 0,5 (FR-TREE-21) */
            rounded?: string[];
        };
        NodesMutation: {
            nodes: components["schemas"]["Node"][];
            deleted_ids?: components["schemas"]["Uuid"][];
            project_version: number;
            totals: components["schemas"]["HoursTotals"];
            branch_statuses: components["schemas"]["BranchStatusChange"][];
            batch_id?: components["schemas"]["Uuid"] | null;
        };
        NodeMove: {
            base_version: number;
            new_parent_id: components["schemas"]["Uuid"];
            after_id?: components["schemas"]["Uuid"] | null;
        };
        /** @description Без O/R/P — сервер подставит суммы детей (BR-TREE-03) */
        NodeCollapse: {
            base_version: number;
            o?: components["schemas"]["HoursInput"];
            r?: components["schemas"]["HoursInput"];
            p?: components["schemas"]["HoursInput"];
        };
        CollapseSuggestion: {
            o: components["schemas"]["DecimalString"];
            r: components["schemas"]["DecimalString"];
            p: components["schemas"]["DecimalString"];
            /** @constant */
            multiplier: 1;
        };
        NodeReview: {
            reviewed: boolean;
        };
        VersionOnly: {
            base_version: number;
        };
        CopyFrom: {
            source_node_id: components["schemas"]["Uuid"];
        };
        TrashBatch: {
            batch_id: components["schemas"]["Uuid"];
            deleted_at: components["schemas"]["Timestamp"];
            deleted_by: components["schemas"]["UserRef"] | null;
            purge_at: components["schemas"]["Timestamp"];
            /** @enum {string} */
            kind: "nodes" | "document";
            root_title: string;
            nodes_count: number;
            document: components["schemas"]["Document"] | null;
            discipline_id: components["schemas"]["Uuid"] | null;
        };
        TrashRestore: {
            target_parent_id?: components["schemas"]["Uuid"] | null;
        };
        HistoryEntry: {
            id: components["schemas"]["Uuid"];
            created_at: components["schemas"]["Timestamp"];
            user: components["schemas"]["UserRef"] | null;
            /** @enum {string} */
            action: "create" | "update" | "move" | "delete" | "restore" | "split" | "collapse" | "review";
            /** @description {поле: [было, стало]}, десятичные — строками */
            changes: Record<string, never>;
            node_version: number;
            project_version: number;
        };
        BranchStatusPut: {
            status: components["schemas"]["BranchStatusValue"];
        };
        Changes: {
            from_version: number;
            to_version: number;
            events: Record<string, never>[];
        };
        Addressee: {
            /** @enum {string} */
            target_type: "user" | "discipline" | "moderators" | "customer";
            target_id: components["schemas"]["Uuid"] | null;
        };
        /** @description Отозванное сообщение: body = "", revoked = true (FR-DISC-06) */
        Message: {
            id: components["schemas"]["Uuid"];
            thread_id: components["schemas"]["Uuid"] | null;
            node_id: components["schemas"]["Uuid"] | null;
            author: components["schemas"]["UserRef"] | null;
            /** @enum {string} */
            kind: "message" | "event" | "customer_answer";
            body: string;
            event: Record<string, never> | null;
            needs_answer: boolean;
            addressees: components["schemas"]["Addressee"][];
            created_at: components["schemas"]["Timestamp"];
            edited_at: components["schemas"]["Timestamp"] | null;
            revoked: boolean;
        };
        Thread: {
            id: components["schemas"]["Uuid"];
            node_id: components["schemas"]["Uuid"] | null;
            opened_by: components["schemas"]["UserRef"];
            /** @enum {string} */
            status: "open" | "resolved";
            resolved_by: components["schemas"]["UserRef"] | null;
            resolved_at: components["schemas"]["Timestamp"] | null;
            is_customer: boolean;
            customer_question_no: number | null;
            customer_status: components["schemas"]["CustomerStatus"] | null;
            sent_at: components["schemas"]["Timestamp"] | null;
            answered_at: components["schemas"]["Timestamp"] | null;
            closed_at: components["schemas"]["Timestamp"] | null;
            withdraw_reason: string | null;
            edited_after_sent: boolean;
            first_message: components["schemas"]["Message"];
            replies_count: number;
        };
        MessageCreate: {
            body: string;
            /** @default false */
            needs_answer: boolean;
            addressees?: components["schemas"]["Addressee"][];
        };
        /** @description Вопрос (needs_answer = true); адресат «customer» делает вопрос заказчику (FR-CQ-01) */
        ThreadCreate: {
            node_id: components["schemas"]["Uuid"] | null;
            body: string;
            addressees?: components["schemas"]["Addressee"][];
        };
        MessagePatch: {
            body: string;
        };
        NodeFeed: {
            items: components["schemas"]["Message"][];
            threads: components["schemas"]["Thread"][];
            next_cursor: string | null;
        };
        ResolveRequest: {
            conclusion?: {
                text: string;
                tag_id: components["schemas"]["Uuid"] | null;
            } | null;
        };
        CustomerQuestion: {
            thread: components["schemas"]["Thread"];
            /** @description Фаза → дисциплина → путь узла */
            path: string[];
            answer: components["schemas"]["Message"] | null;
        };
        CqExportRequest: {
            thread_ids: components["schemas"]["Uuid"][];
            /** @enum {string} */
            format: "xlsx" | "docx";
        };
        CqAnswer: {
            body: string;
        };
        CqWithdraw: {
            reason: string;
        };
        CqEdit: {
            body: string;
        };
        StatsMoney: {
            cost_by_discipline?: {
                discipline_id: components["schemas"]["Uuid"] | null;
                cost_rub: components["schemas"]["MoneyString"] | null;
            }[];
            cost_by_phase?: {
                phase_id: components["schemas"]["Uuid"];
                cost_rub: components["schemas"]["MoneyString"] | null;
            }[];
            figures?: {
                e?: components["schemas"]["MoneyFigure"];
                p80?: components["schemas"]["MoneyFigure"];
                p90?: components["schemas"]["MoneyFigure"];
            };
            dynamics?: {
                date: components["schemas"]["Date"];
                quote_cur: components["schemas"]["MoneyString"] | null;
            }[];
            snapshots?: {
                snapshot_id: components["schemas"]["Uuid"];
                quote_cur: components["schemas"]["MoneyString"] | null;
            }[];
        };
        /** @description Статистика (10.1). Блок money — только с money.read и TOTP (G-03) */
        Stats: {
            project_version: number;
            readiness: {
                phase_id: components["schemas"]["Uuid"];
                discipline_id: components["schemas"]["Uuid"];
                e: components["schemas"]["HoursString"];
                status: components["schemas"]["BranchStatusValue"];
                last_change_at: components["schemas"]["Timestamp"] | null;
                flags: ("large" | "wide_fork" | "open_question" | "no_expert" | "overdue")[];
                overdue_working_days: number | null;
            }[];
            totals: {
                by_phase: {
                    phase_id: components["schemas"]["Uuid"];
                    hours: components["schemas"]["HoursTotals"];
                    share_pct: components["schemas"]["DecimalString"] | null;
                }[];
                by_discipline: {
                    discipline_id: components["schemas"]["Uuid"];
                    hours: components["schemas"]["HoursTotals"];
                    share_pct: components["schemas"]["DecimalString"] | null;
                }[];
                works: components["schemas"]["HoursTotals"];
                pm: components["schemas"]["HoursTotals"];
                total: components["schemas"]["HoursTotals"];
                quote_figure: components["schemas"]["QuoteFigure"];
                duration_weeks: number | null;
            };
            ratios: {
                ratio_id: components["schemas"]["Uuid"];
                pct: components["schemas"]["DecimalString"] | null;
                min_pct: components["schemas"]["DecimalString"];
                max_pct: components["schemas"]["DecimalString"];
                verdict: ("ok" | "below" | "above") | null;
            }[];
            volumes: {
                type_id: components["schemas"]["Uuid"];
                name: string;
                count: number;
            }[];
            candidates: {
                large: {
                    node_id: components["schemas"]["Uuid"];
                    e_unit: components["schemas"]["HoursString"];
                    e: components["schemas"]["HoursString"];
                    repeating: boolean;
                }[];
                wide_fork: {
                    node_id: components["schemas"]["Uuid"];
                    ratio_pct: components["schemas"]["DecimalString"];
                }[];
            };
            tag_lists: {
                /** @enum {string} */
                category: "assumption" | "constraint" | "risk" | "tech";
                items: {
                    node_id: components["schemas"]["Uuid"];
                    tag_id: components["schemas"]["Uuid"];
                    text: string;
                    path: string[];
                }[];
            }[];
            reviewed: {
                discipline_id: components["schemas"]["Uuid"];
                reviewed_pct: components["schemas"]["DecimalString"] | null;
                self_review_pct: components["schemas"]["DecimalString"] | null;
            }[];
            dynamics: {
                date: components["schemas"]["Date"];
                e: components["schemas"]["HoursString"] | null;
                p80: components["schemas"]["HoursString"] | null;
            }[];
            money?: components["schemas"]["StatsMoney"];
        };
        SnapshotMoney: {
            quote_cur: components["schemas"]["MoneyString"] | null;
            currency: string;
        };
        Snapshot: {
            id: components["schemas"]["Uuid"];
            name: string;
            description: string;
            created_by: components["schemas"]["UserRef"];
            created_at: components["schemas"]["Timestamp"];
            is_invalid: boolean;
            project_version: number;
            totals: components["schemas"]["HoursTotals"];
            money?: components["schemas"]["SnapshotMoney"];
        };
        SnapshotCreate: {
            name: string;
            description?: string;
        };
        /** @description Влияние ставок и курса отдельной строкой (FR-SNAP-03) */
        DiffMoney: {
            rows: {
                node_id: components["schemas"]["Uuid"] | null;
                delta_cost_rub: components["schemas"]["MoneyString"] | null;
            }[];
            rates_effect_rub: components["schemas"]["DecimalString"] | null;
            exchange_effect_cur: components["schemas"]["DecimalString"] | null;
            total_delta_rub: components["schemas"]["DecimalString"] | null;
        };
        Diff: {
            base: {
                snapshot_id: components["schemas"]["Uuid"] | null;
                label: string;
            };
            with: {
                snapshot_id: components["schemas"]["Uuid"] | null;
                label: string;
            };
            rows: {
                node_id: components["schemas"]["Uuid"];
                /** @enum {string} */
                change: "added" | "removed" | "changed" | "moved";
                title: string;
                path: string[];
                delta_e: components["schemas"]["HoursString"];
                fields: string[];
                last_changed_by: components["schemas"]["UserRef"] | null;
            }[];
            totals_delta: components["schemas"]["HoursTotals"];
            money?: components["schemas"]["DiffMoney"];
        };
        /**
         * @description Виды выгрузок — contracts/exports.yaml (EXP-001)
         * @enum {string}
         */
        ExportKind: "hours_xlsx" | "money_xlsx" | "cq_xlsx" | "cq_docx" | "snapshot_diff_xlsx" | "stats_tab_xlsx" | "assumptions_docx" | "portfolio_xlsx" | "audit_csv";
        ExportCreate: {
            /** @enum {string} */
            kind: "hours_xlsx" | "money_xlsx";
            snapshot_id?: components["schemas"]["Uuid"] | null;
        };
        ExportJob: {
            id: components["schemas"]["Uuid"];
            kind: components["schemas"]["ExportKind"];
            /** @enum {string} */
            status: "pending" | "ready";
            file_name: string | null;
            download_url: string | null;
            expires_at: components["schemas"]["Timestamp"];
        };
        Notification: {
            id: components["schemas"]["Uuid"];
            /** @description Вид из contracts/notifications.yaml (NTF-001) */
            kind: string;
            project_id: components["schemas"]["Uuid"] | null;
            node_id: components["schemas"]["Uuid"] | null;
            payload: Record<string, never>;
            created_at: components["schemas"]["Timestamp"];
            read_at: components["schemas"]["Timestamp"] | null;
        };
        NotificationsRead: {
            ids?: components["schemas"]["Uuid"][];
            /** @default false */
            all: boolean;
        };
        NotificationList: {
            items: components["schemas"]["Notification"][];
            unread: number;
            next_cursor: string | null;
        };
        PortfolioItemMoney: {
            currency: string;
            quote_cur: components["schemas"]["MoneyString"] | null;
            quote_rub: components["schemas"]["MoneyString"] | null;
            cost_rub: components["schemas"]["MoneyString"] | null;
            contract_amount: components["schemas"]["MoneyString"] | null;
            rates_missing: boolean;
        };
        PortfolioItem: {
            id: components["schemas"]["Uuid"];
            name: string;
            customer: string;
            moderators: components["schemas"]["UserRef"][];
            presales: components["schemas"]["UserRef"][];
            status: components["schemas"]["ProjectStatus"];
            outcome: components["schemas"]["Outcome"];
            quote_figure: components["schemas"]["QuoteFigure"];
            quote_hours: components["schemas"]["HoursString"] | null;
            no_moderator: boolean;
            created_at: components["schemas"]["Timestamp"];
            updated_at: components["schemas"]["Timestamp"];
            money: components["schemas"]["PortfolioItemMoney"];
        };
        PortfolioSummary: {
            period: {
                from: components["schemas"]["Date"];
                to: components["schemas"]["Date"];
            };
            by_status: Record<string, never>;
            by_outcome: Record<string, never>;
            won_share_count_pct: components["schemas"]["DecimalString"] | null;
            won_share_money_pct: components["schemas"]["DecimalString"] | null;
            sum_won_cur: components["schemas"]["MoneyString"] | null;
            sum_lost_cur: components["schemas"]["MoneyString"] | null;
            sum_in_progress_cur: components["schemas"]["MoneyString"] | null;
            loss_reasons: {
                loss_reason_id: components["schemas"]["Uuid"] | null;
                name: string;
                count: number;
                texts: string[];
            }[];
            contract_to_quote_median_pct: components["schemas"]["DecimalString"] | null;
            by_month: {
                month: string;
                won: number;
                lost: number;
                cancelled: number;
            }[];
            first_snapshot_median_days: components["schemas"]["DecimalString"] | null;
        };
        PortfolioExport: {
            from: components["schemas"]["Date"];
            to: components["schemas"]["Date"];
        };
    };
    responses: {
        /** @description Некорректный запрос. Коды: MALFORMED_REQUEST, CURSOR_INVALID */
        Problem400: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Требуется вход или неверные данные. Коды: UNAUTHENTICATED, LOGIN_FAILED, LOGIN_STEP_EXPIRED, TOTP_INVALID, STEP_UP_FAILED */
        Problem401: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Нет доступа. Коды: TOTP_ENROLL_REQUIRED, TOTP_REQUIRED, STEP_UP_REQUIRED, CSRF_FAILED, FORBIDDEN */
        Problem403: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Не найдено. Коды: NOT_FOUND */
        Problem404: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Конфликт с состоянием. Коды: FIELD_CONFLICT, NODES_LIMIT, RESTORE_TARGET_UNAVAILABLE, BRANCH_NOT_READY, BRANCH_NOT_EMPTY, INVALID_TRANSITION, PROJECT_STATUS_CONFLICT, CONFIRMATION_REQUIRED, CROSS_CUTTING_PHASE_LOCKED, LAST_MODERATOR, LAST_SUPERADMIN, SUPERADMIN_LIMIT, ROLE_INCOMPATIBLE, ALREADY_EXISTS, USER_NOT_BLOCKED, AD_USER_NOT_IN_GROUP, DICTIONARY_IN_USE, SETUP_ALREADY_COMPLETED, AD_CHECKS_REQUIRED, MODE_SWITCH_NOT_ALLOWED, MODE_SWITCH_UNRESOLVED, MESSAGE_HAS_REPLIES, PROJECT_STORAGE_LIMIT, DOCUMENT_NOT_AVAILABLE, EXPORT_FAILED */
        Problem409: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Больше недоступно. Коды: TOKEN_INVALID, VERSION_TOO_OLD, EXPORT_EXPIRED */
        Problem410: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Слишком большой запрос. Коды: PAYLOAD_TOO_LARGE */
        Problem413: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Недопустимый тип. Коды: UNSUPPORTED_MEDIA_TYPE */
        Problem415: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Ошибка в данных. Коды: VALIDATION_FAILED, VALUE_OUT_OF_RANGE, PASSWORD_POLICY_VIOLATION, CURRENT_PASSWORD_INVALID, NODE_HAS_CHILDREN, DEPTH_LIMIT, MEMBER_ROLE_REQUIRED, MEMBER_LIMIT */
        Problem422: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Занято другим пользователем. Коды: CELL_LOCKED */
        Problem423: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Слишком много запросов. Коды: RATE_LIMITED, LOGIN_LOCKED, REMIND_TOO_OFTEN */
        Problem429: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Внутренняя ошибка. Коды: INTERNAL_ERROR */
        Problem500: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Недоступно. Коды: SERVICE_UNAVAILABLE, APP_SETUP_IN_PROGRESS, AUTH_SERVICE_UNAVAILABLE */
        Problem503: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
    };
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
};
export type $defs = Record<string, never>;
export interface operations {
    login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            401: components["responses"]["Problem401"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
            503: components["responses"]["Problem503"];
        };
    };
    loginTotp: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TotpLoginRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            401: components["responses"]["Problem401"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    logout: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    totpEnrollStart: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TotpEnrollStart"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    totpEnrollConfirm: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TotpCode"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupCodes"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    stepUp: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StepUpRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StepUpResponse"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    activate: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TokenPassword"];
            };
        };
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            410: components["responses"]["Problem410"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    passwordForgot: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ForgotRequest"];
            };
        };
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    passwordReset: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TokenPassword"];
            };
        };
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            410: components["responses"]["Problem410"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getMe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    patchMe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MePatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listMySessions: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Session"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteMySessions: {
        parameters: {
            query?: {
                /** @description Одна сессия; без параметра — все, кроме текущей */
                id?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    changePassword: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PasswordChange"];
            };
        };
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    enableTotp: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    code?: string;
                };
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TotpEnrollStart"] | components["schemas"]["BackupCodes"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    disableTotp: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    regenerateBackupCodes: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackupCodes"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getNotificationSettings: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationSettings"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    putNotificationSettings: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotificationSettings"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationSettings"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getViewState: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ViewState"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putViewState: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ViewState"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ViewState"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            413: components["responses"]["Problem413"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getSetupStep: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                step: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetupStep"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    postSetupStep: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                step: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetupStepWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetupStep"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getHealth: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Health"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    getSettings: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                section: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsSection"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putSettings: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                section: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsSection"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adTestConnection: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    values?: Record<string, never>;
                };
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdTestResult"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adTestLogin: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdTestLogin"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdTestResult"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    switchMode: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SwitchModeRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwitchReport"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    switchModeResolve: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SwitchResolve"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwitchReport"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listAdmins: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["AdminAccount"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    createAdmin: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminAccountCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivationLink"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    demoteAdmin: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    patchAdmin: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminAccountPatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminAccount"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    systemResetPassword: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivationLink"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    systemResetTotp: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    anonymizeUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    systemRegistry: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["RegistryProject"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    listAudit: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                from?: components["schemas"]["Timestamp"];
                to?: components["schemas"]["Timestamp"];
                user_id?: components["schemas"]["Uuid"];
                event_type?: string;
                result?: "success" | "failure" | "denied";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["AuditEntry"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    exportAudit: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AuditExportRequest"];
            };
        };
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listUsers: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                q?: string;
                status?: "active" | "blocked" | "pending_password" | "anonymized";
                role?: components["schemas"]["SystemRole"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["User"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createUser: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        user: components["schemas"]["User"];
                        activation: components["schemas"]["ActivationLink"] | null;
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    patchUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserPatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adminResetPassword: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivationLink"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adminResetTotp: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    blockUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BlockRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    unblockUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    replaceEverywhere: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplaceRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReplaceReport"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adSearch: {
        parameters: {
            query: {
                q: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["AdSearchItem"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
            503: components["responses"]["Problem503"];
        };
    };
    listPhases: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Phase"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createPhases: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PhaseWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Phase"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deletePhases: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updatePhases: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PhaseWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Phase"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listDisciplines: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Discipline"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createDisciplines: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DisciplineWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Discipline"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteDisciplines: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateDisciplines: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DisciplineWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Discipline"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listNodeTypes: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["NodeType"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createNodeTypes: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeTypeWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeType"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteNodeTypes: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateNodeTypes: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeTypeWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeType"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listProfiles: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Profile"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createProfiles: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteProfiles: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateProfiles: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listRatios: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Ratio"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createRatios: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RatioWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ratio"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteRatios: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateRatios: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RatioWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ratio"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listTags: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Tag"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createTags: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TagWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Tag"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteTags: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateTags: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TagWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Tag"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listCurrencies: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Currency"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createCurrencies: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CurrencyWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Currency"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteCurrencies: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateCurrencies: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CurrencyWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Currency"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listVatRates: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["VatRate"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createVatRates: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VatRateWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VatRate"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteVatRates: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateVatRates: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VatRateWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VatRate"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listLossReasons: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["LossReason"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createLossReasons: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LossReasonWrite"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LossReason"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteLossReasons: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    updateLossReasons: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LossReasonWrite"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LossReason"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listCalendar: {
        parameters: {
            query?: {
                year?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["CalendarYear"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    uploadCalendar: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": {
                    /** Format: binary */
                    file: string;
                    /** @default true */
                    dry_run?: boolean;
                };
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarPreview"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            413: components["responses"]["Problem413"];
            415: components["responses"]["Problem415"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    putCalendarYear: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                year: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalendarYear"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarYear"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteCalendarYear: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                year: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listProposedTypes: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["ProposedType"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    acceptProposedType: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeType"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    mergeProposedType: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MergeRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeType"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    rejectProposedType: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    adminRegistry: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                without_moderator?: boolean;
                status?: components["schemas"]["ProjectStatus"];
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["RegistryProject"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    transferModerators: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModeratorsTransfer"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    openSupportSession: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SupportSessionCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SupportSession"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    portfolioProjects: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                status?: components["schemas"]["ProjectStatus"];
                outcome?: components["schemas"]["Outcome"];
                moderator_id?: components["schemas"]["Uuid"];
                from?: components["schemas"]["Date"];
                to?: components["schemas"]["Date"];
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["PortfolioItem"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    portfolioSummary: {
        parameters: {
            query: {
                from: components["schemas"]["Date"];
                to: components["schemas"]["Date"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioSummary"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    portfolioExport: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioExport"];
            };
        };
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    joinAsModerator: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listProjects: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                status?: components["schemas"]["ProjectStatus"];
                role?: components["schemas"]["ProjectRole"];
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["ProjectListItem"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    createProject: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectVersioned"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getProject: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Project"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    patchProject: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectPatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectVersioned"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    copyProject: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CopyProject"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectVersioned"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    changeProjectStatus: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StatusChange"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatusChangeResult"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getMembers: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putMembers: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MembersPut"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    addDiscipline: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DisciplineAdd"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    removeDiscipline: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
                discipline_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    patchDisciplineProfile: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
                discipline_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DisciplineProfilePatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectDiscipline"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    projectAdSearch: {
        parameters: {
            query: {
                q: string;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["AdSearchItem"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
            503: components["responses"]["Problem503"];
        };
    };
    projectAdCreate: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectAdCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
            503: components["responses"]["Problem503"];
        };
    };
    replaceMember: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
                user_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MemberReplace"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Member"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    createLocalNodeType: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocalNodeType"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeType"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    remindNotStarted: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RemindResult"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getMoney: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectMoney"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putMoney: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectMoneyPut"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectMoney"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getOutcome: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectOutcome"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putOutcome: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectOutcomePut"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectOutcome"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listDocuments: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentList"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    uploadDocument: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": {
                    /** Format: binary */
                    file: string;
                };
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Document"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            413: components["responses"]["Problem413"];
            415: components["responses"]["Problem415"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    downloadDocument: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Файл */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/octet-stream": string;
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteDocument: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    restoreDocument: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Document"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getJournal: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["JournalEntry"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    suggestAddressees: {
        parameters: {
            query: {
                q: string;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["SuggestItem"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    listNotes: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                node_id?: components["schemas"]["Uuid"];
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Note"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    createNote: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Note"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    patchNote: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotePatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Note"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getTree: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Tree"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    getChanges: {
        parameters: {
            query: {
                since: number;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Changes"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            410: components["responses"]["Problem410"];
            500: components["responses"]["Problem500"];
        };
    };
    createNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    deleteNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    patchNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                /**
                 * @example {
                 *       "base_version": 7,
                 *       "changes": {
                 *         "r": "16",
                 *         "p": "30"
                 *       }
                 *     }
                 */
                "application/json": components["schemas"]["NodePatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "node": {
                     *         "id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e6f",
                     *         "parent_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e60",
                     *         "kind": "item",
                     *         "phase_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e61",
                     *         "discipline_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e62",
                     *         "type_id": null,
                     *         "title": "Авторизация",
                     *         "position": "a0",
                     *         "comment_lines": null,
                     *         "o": "8",
                     *         "r": "16",
                     *         "p": "30",
                     *         "multiplier": 1,
                     *         "e": "17.00",
                     *         "sigma": "3.67",
                     *         "version": 8
                     *       },
                     *       "project_version": 1051,
                     *       "ancestors": [
                     *         {
                     *           "id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e60",
                     *           "e": "97.00",
                     *           "sigma": "10.84"
                     *         }
                     *       ],
                     *       "totals": {
                     *         "e": "411.62",
                     *         "p80": "430.90",
                     *         "p90": "440.98"
                     *       },
                     *       "branch_status": {
                     *         "phase_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e61",
                     *         "discipline_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e62",
                     *         "status": "draft",
                     *         "was": "done"
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["NodeMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            /** @description Конфликт поля (FIELD_CONFLICT) или состояния проекта */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "type": "https://estimator.local/problems/field-conflict",
                     *       "title": "Значение уже изменено",
                     *       "status": 409,
                     *       "code": "FIELD_CONFLICT",
                     *       "error_id": "0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e70",
                     *       "conflicts": [
                     *         {
                     *           "field": "r",
                     *           "current": "18",
                     *           "changed_by": "П. Петров",
                     *           "changed_at": "2026-11-03T12:01:44Z"
                     *         }
                     *       ],
                     *       "current_version": 9
                     *     }
                     */
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            422: components["responses"]["Problem422"];
            423: components["responses"]["Problem423"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    moveNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeMove"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    splitNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VersionOnly"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    collapseSuggestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CollapseSuggestion"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    collapseNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeCollapse"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    reviewNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NodeReview"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    duplicateNode: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    copyBranchFrom: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CopyFrom"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getTrash: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["TrashBatch"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    restoreTrash: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                batch_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TrashRestore"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodesMutation"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getNodeHistory: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["HistoryEntry"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    putBranchStatus: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
                /** @description id фазы */
                phase: components["schemas"]["Uuid"];
                /** @description id дисциплины */
                discipline: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BranchStatusPut"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BranchStatusChange"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listThreads: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                status?: "open" | "resolved";
                addressee?: "me" | "any";
                discipline_id?: components["schemas"]["Uuid"];
                node_id?: components["schemas"]["Uuid"];
                project_level?: boolean;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Thread"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    createThread: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listNodeMessages: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NodeFeed"];
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    postNodeMessage: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MessageCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Message"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    replyThread: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MessageCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Message"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    editMessage: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MessagePatch"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Message"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    revokeMessage: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Message"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    resolveThread: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResolveRequest"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    reopenThread: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listCustomerQuestions: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                status?: components["schemas"]["CustomerStatus"];
                discipline_id?: components["schemas"]["Uuid"];
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["CustomerQuestion"][];
                        next_cursor: string | null;
                    };
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    exportCustomerQuestions: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CqExportRequest"];
            };
        };
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    answerCustomerQuestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CqAnswer"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    withdrawCustomerQuestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CqWithdraw"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    editCustomerQuestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CqEdit"];
            };
        };
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getStats: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Stats"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    exportStatsTab: {
        parameters: {
            query: {
                format: "xlsx";
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
                tab: "readiness" | "totals" | "ratios" | "volumes" | "candidates" | "tags" | "discussions" | "customer_questions" | "reviewed" | "snapshots" | "dynamics";
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    exportAssumptions: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    listSnapshots: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Snapshot"][];
                    };
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    createSnapshot: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SnapshotCreate"];
            };
        };
        responses: {
            /** @description Успех */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Snapshot"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    invalidateSnapshot: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Snapshot"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    diffSnapshot: {
        parameters: {
            query: {
                /** @description id снимка или «current» */
                with: string;
            };
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Diff"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            500: components["responses"]["Problem500"];
        };
    };
    exportDiff: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    with: string;
                };
            };
        };
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    createExport: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExportCreate"];
            };
        };
        responses: {
            /** @description Успех */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    getExport: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportJob"];
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            409: components["responses"]["Problem409"];
            410: components["responses"]["Problem410"];
            500: components["responses"]["Problem500"];
        };
    };
    downloadExport: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Файл */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/octet-stream": string;
                };
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            404: components["responses"]["Problem404"];
            410: components["responses"]["Problem410"];
            500: components["responses"]["Problem500"];
        };
    };
    listNotifications: {
        parameters: {
            query?: {
                cursor?: string;
                limit?: number;
                unread?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Успех */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationList"];
                };
            };
            400: components["responses"]["Problem400"];
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
    markNotificationsRead: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotificationsRead"];
            };
        };
        responses: {
            /** @description Выполнено */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            422: components["responses"]["Problem422"];
            429: components["responses"]["Problem429"];
            500: components["responses"]["Problem500"];
        };
    };
    websocket: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Switching Protocols */
            101: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Problem401"];
            403: components["responses"]["Problem403"];
            500: components["responses"]["Problem500"];
        };
    };
}
