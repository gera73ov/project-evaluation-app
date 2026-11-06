"""Каталог кодов ошибок API v1 — копия ``contracts/errors.yaml`` (API-001).

Образ ``api`` собирается без каталога ``contracts/``, поэтому код, статус, ``type``, ``title`` и
объявленные расширения продублированы здесь; ``tests/unit/api/test_error_catalog.py`` сверяет
копию с контрактом. Новый код добавляется в errors.yaml и сюда одним PR (api-conventions.md 5 п. 6).
"""

from __future__ import annotations

from typing import NamedTuple

TYPE_BASE = "https://estimator.local/problems/"


class ErrorSpec(NamedTuple):
    code: str
    status: int
    type: str
    title: str
    extensions: tuple[str, ...]


_SPECS = (
    ErrorSpec("MALFORMED_REQUEST", 400, "malformed-request", "Некорректный запрос", ()),
    ErrorSpec("CURSOR_INVALID", 400, "cursor-invalid", "Неверный курсор пагинации", ()),
    ErrorSpec("VALIDATION_FAILED", 422, "validation-failed", "Ошибка в данных", ("errors",)),
    ErrorSpec(
        "VALUE_OUT_OF_RANGE",
        422,
        "value-out-of-range",
        "Значение вне допустимого диапазона",
        ("field", "max", "min"),
    ),
    ErrorSpec(
        "PAYLOAD_TOO_LARGE", 413, "payload-too-large", "Слишком большой запрос", ("limit_bytes",)
    ),
    ErrorSpec(
        "UNSUPPORTED_MEDIA_TYPE", 415, "unsupported-media-type", "Недопустимый тип файла", ()
    ),
    ErrorSpec("RATE_LIMITED", 429, "rate-limited", "Слишком много запросов", ("retry_after",)),
    ErrorSpec("INTERNAL_ERROR", 500, "internal-error", "Внутренняя ошибка", ()),
    ErrorSpec("SERVICE_UNAVAILABLE", 503, "service-unavailable", "Сервис временно недоступен", ()),
    ErrorSpec(
        "APP_SETUP_IN_PROGRESS", 503, "app-setup-in-progress", "Приложение настраивается", ()
    ),
    ErrorSpec("UNAUTHENTICATED", 401, "unauthenticated", "Требуется вход", ()),
    ErrorSpec("LOGIN_FAILED", 401, "login-failed", "Неверный логин или пароль", ("auth_mode",)),
    ErrorSpec("LOGIN_LOCKED", 429, "login-locked", "Вход временно заблокирован", ()),
    ErrorSpec(
        "AUTH_SERVICE_UNAVAILABLE",
        503,
        "auth-service-unavailable",
        "Сервис аутентификации недоступен",
        (),
    ),
    ErrorSpec("LOGIN_STEP_EXPIRED", 401, "login-step-expired", "Время на ввод кода истекло", ()),
    ErrorSpec("TOTP_INVALID", 401, "totp-invalid", "Неверный код", ()),
    ErrorSpec("TOTP_ENROLL_REQUIRED", 403, "totp-enroll-required", "Подключите второй фактор", ()),
    ErrorSpec("TOTP_REQUIRED", 403, "totp-required", "Подтвердите вход кодом", ()),
    ErrorSpec("STEP_UP_REQUIRED", 403, "step-up-required", "Подтвердите действие", ()),
    ErrorSpec("STEP_UP_FAILED", 401, "step-up-failed", "Подтверждение не принято", ()),
    ErrorSpec("CSRF_FAILED", 403, "csrf-failed", "Запрос отклонён", ()),
    ErrorSpec("TOKEN_INVALID", 410, "token-invalid", "Ссылка недействительна", ()),
    ErrorSpec(
        "PASSWORD_POLICY_VIOLATION",
        422,
        "password-policy-violation",
        "Пароль не подходит",
        ("violations",),
    ),
    ErrorSpec(
        "CURRENT_PASSWORD_INVALID", 422, "current-password-invalid", "Неверный текущий пароль", ()
    ),
    ErrorSpec("FORBIDDEN", 403, "forbidden", "Нет доступа", ("permission",)),
    ErrorSpec("NOT_FOUND", 404, "not-found", "Не найдено", ()),
    ErrorSpec(
        "FIELD_CONFLICT",
        409,
        "field-conflict",
        "Значение уже изменено",
        ("conflicts", "current_version"),
    ),
    ErrorSpec(
        "CELL_LOCKED",
        423,
        "cell-locked",
        "Ячейку редактирует другой пользователь",
        ("field", "locked_by", "node_id"),
    ),
    ErrorSpec("NODE_HAS_CHILDREN", 422, "node-has-children", "У узла есть дочерние строки", ()),
    ErrorSpec("DEPTH_LIMIT", 422, "depth-limit", "Слишком глубокая вложенность", ("max_depth",)),
    ErrorSpec(
        "NODES_LIMIT",
        409,
        "nodes-limit",
        "Достигнут предел узлов проекта",
        ("current", "limit", "requested"),
    ),
    ErrorSpec(
        "RESTORE_TARGET_UNAVAILABLE",
        409,
        "restore-target-unavailable",
        "Прежнее место недоступно",
        ("discipline_id", "reason"),
    ),
    ErrorSpec(
        "BRANCH_NOT_READY", 409, "branch-not-ready", "Ветку нельзя отметить «готово»", ("node_ids",)
    ),
    ErrorSpec("BRANCH_NOT_EMPTY", 409, "branch-not-empty", "Ветка не пустая", ()),
    ErrorSpec(
        "INVALID_TRANSITION", 409, "invalid-transition", "Переход недоступен", ("from", "to")
    ),
    ErrorSpec(
        "PROJECT_STATUS_CONFLICT",
        409,
        "project-status-conflict",
        "Недоступно в этом статусе проекта",
        ("project_status",),
    ),
    ErrorSpec(
        "CONFIRMATION_REQUIRED",
        409,
        "confirmation-required",
        "Требуется подтверждение",
        ("affected", "consequence"),
    ),
    ErrorSpec(
        "CROSS_CUTTING_PHASE_LOCKED",
        409,
        "cross-cutting-phase-locked",
        "Фазу «Управление проектом» не выключают",
        (),
    ),
    ErrorSpec(
        "VERSION_TOO_OLD", 410, "version-too-old", "Нужна полная перезагрузка", ("current_version",)
    ),
    ErrorSpec("LAST_MODERATOR", 409, "last-moderator", "Последний модератор проекта", ()),
    ErrorSpec("LAST_SUPERADMIN", 409, "last-superadmin", "Последний суперадминистратор", ()),
    ErrorSpec("SUPERADMIN_LIMIT", 409, "superadmin-limit", "Суперадминистраторов уже три", ()),
    ErrorSpec(
        "ROLE_INCOMPATIBLE", 409, "role-incompatible", "Роли несовместимы", ("conflicting_roles",)
    ),
    ErrorSpec(
        "MEMBER_ROLE_REQUIRED",
        422,
        "member-role-required",
        "У пользователя нет нужной системной роли",
        ("required_role",),
    ),
    ErrorSpec(
        "MEMBER_LIMIT", 422, "member-limit", "Превышено число участников роли", ("limit", "role")
    ),
    ErrorSpec("ALREADY_EXISTS", 409, "already-exists", "Уже существует", ("field",)),
    ErrorSpec("USER_NOT_BLOCKED", 409, "user-not-blocked", "Пользователь не заблокирован", ()),
    ErrorSpec("AD_USER_NOT_IN_GROUP", 409, "ad-user-not-in-group", "Нет в группе доступа", ()),
    ErrorSpec("DICTIONARY_IN_USE", 409, "dictionary-in-use", "Запись справочника используется", ()),
    ErrorSpec(
        "SETUP_ALREADY_COMPLETED",
        409,
        "setup-already-completed",
        "Первичная настройка уже завершена",
        (),
    ),
    ErrorSpec(
        "AD_CHECKS_REQUIRED",
        409,
        "ad-checks-required",
        "Сначала проверьте подключение и вход",
        ("missing",),
    ),
    ErrorSpec(
        "MODE_SWITCH_NOT_ALLOWED",
        409,
        "mode-switch-not-allowed",
        "Переход недоступен в интерфейсе",
        (),
    ),
    ErrorSpec(
        "MODE_SWITCH_UNRESOLVED",
        409,
        "mode-switch-unresolved",
        "Есть нерешённые совпадения",
        ("unresolved",),
    ),
    ErrorSpec("MESSAGE_HAS_REPLIES", 409, "message-has-replies", "На сообщение уже ответили", ()),
    ErrorSpec(
        "PROJECT_STORAGE_LIMIT",
        409,
        "project-storage-limit",
        "Место проекта закончилось",
        ("limit_bytes", "used_bytes"),
    ),
    ErrorSpec(
        "DOCUMENT_NOT_AVAILABLE",
        409,
        "document-not-available",
        "Документ недоступен",
        ("scan_status",),
    ),
    ErrorSpec("EXPORT_EXPIRED", 410, "export-expired", "Файл выгрузки удалён", ()),
    ErrorSpec("EXPORT_FAILED", 409, "export-failed", "Выгрузка не удалась", ()),
    ErrorSpec(
        "REMIND_TOO_OFTEN", 429, "remind-too-often", "Напоминание уже отправлено", ("retry_after",)
    ),
)

#: Код → описание
CATALOG: dict[str, ErrorSpec] = {spec.code: spec for spec in _SPECS}
