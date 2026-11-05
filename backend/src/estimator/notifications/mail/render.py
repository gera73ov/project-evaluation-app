"""Шаблоны писем (NTF-002; FR-NOTIF-02, FR-NOTIF-03, Q-37).

Письмо содержит только название проекта, счётчики и ссылку в приложение: в шаблон можно
передать лишь поля ``email_fields`` из contracts/notifications.yaml (:data:`EMAIL_FIELDS`).
Шаблоны — ``notifications/templates/<вид>.txt`` (блоки ``subject`` и ``body``) и
``<вид>.html``; HTML с автоэкранированием, неизвестная переменная — ошибка (StrictUndefined).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from estimator.notifications.mail.config import SmtpConfig

#: Поля писем — ровно ``emails.<вид>.email_fields`` контракта (проверяется тестом).
EMAIL_FIELDS: dict[str, frozenset[str]] = {
    "digest": frozenset({"projects", "total"}),
    "questions_batch": frozenset({"projects"}),
    "assigned_to_project": frozenset({"project_name", "link"}),
    "password_setup": frozenset({"link", "expires_hours"}),
    "password_reset": frozenset({"link", "expires_minutes"}),
    "new_device_login": frozenset({"browser", "subnet", "time", "link"}),
    "remind_not_started": frozenset({"project_name", "deadline", "link"}),
    "security_alert": frozenset({"alert", "time", "actor_login", "ip", "link"}),
}
#: Служебное письмо мастера настройки «Отправить тестовое письмо» (7.1 шаг 2); в каталог
#: уведомлений не входит — его не получают пользователи, только адрес, введённый в мастере.
TEST_EMAIL = "smtp_test"
ALL_FIELDS: dict[str, frozenset[str]] = {**EMAIL_FIELDS, TEST_EMAIL: frozenset({"link"})}
#: Поля элементов списка ``projects`` (digest, questions_batch).
PROJECT_ITEM_FIELDS = frozenset({"project_name", "counters", "link", "questions", "answers"})

#: Подписи счётчиков сводки по видам уведомлений (contracts/notifications.yaml, kinds).
KIND_LABELS: dict[str, str] = {
    "question_to_me": "вопросы вам",
    "answer_to_my_question": "ответы на ваши вопросы",
    "moderator_change": "изменения модератора в ваших строках",
    "branch_back_to_draft": "ветки, вернувшиеся в черновик",
    "assigned_to_project": "назначения в проект",
}

#: Тексты оповещений ИБ (audit-events.yaml, security_alerts; SEC-AUTH-07).
ALERT_LABELS: dict[str, str] = {
    "smtp_changed": "Изменены настройки почтового сервера",
    "auth_mode_switched": "Изменён способ входа",
    "ad_settings_changed": "Изменены параметры подключения к AD",
    "privileged_account_changed": "Изменена учётная запись суперадминистратора или администратора",
    "privileged_password_reset": "Сброшен пароль суперадминистратора или администратора",  # nosec B105 — подпись, не пароль
    "privileged_totp_reset": "Сброшен TOTP суперадминистратора или администратора",
    "security_auditor_role": "Выдана или снята роль «Аудитор ИБ»",
    "mfa_requirement_disabled": "Отключён обязательный TOTP для роли",
    "admin_networks_changed": "Изменены сетевые ограничения админки",
    "superadmin_login_failures": "5 неудачных входов подряд по логину суперадминистратора",
    "login_failures_burst": "Больше 20 неудачных входов за час по одному логину",
    "audit_chain_broken": "Нарушена целостность журнала аудита",
}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа по правилам русского языка: 1 вопрос, 2 вопроса, 5 вопросов."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("estimator.notifications", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    env.globals.update(kind_label=KIND_LABELS.get, alert_label=ALERT_LABELS.get, plural=plural)
    return env


_env = _environment()


def render_email(kind: str, fields: Mapping[str, Any]) -> RenderedEmail:
    """Отрисовать письмо. Лишние поля запрещены: так в письмо не попадёт лишнее (FR-NOTIF-03)."""
    allowed = ALL_FIELDS.get(kind)
    if allowed is None:
        raise ValueError(f"неизвестный вид письма: {kind}")
    extra = set(fields) - allowed
    if extra:
        raise ValueError(f"поля не разрешены для письма {kind}: {sorted(extra)}")
    missing = allowed - set(fields)
    if missing:
        raise ValueError(f"не переданы поля письма {kind}: {sorted(missing)} (пустое — None)")
    for project in fields.get("projects") or []:
        extra = set(project) - PROJECT_ITEM_FIELDS
        if extra:
            raise ValueError(f"поля не разрешены в projects письма {kind}: {sorted(extra)}")
    context = {name: fields[name] for name in allowed}
    text_tpl = _env.get_template(f"{kind}.txt")
    text_ctx = text_tpl.new_context(context)
    subject = "".join(text_tpl.blocks["subject"](text_ctx)).strip()
    body = "".join(text_tpl.blocks["body"](text_tpl.new_context(context))).strip() + "\n"
    html = _env.get_template(f"{kind}.html").render(context, subject=subject)
    return RenderedEmail(subject=" ".join(subject.split()), text=body, html=html)


def build_message(config: SmtpConfig, to: str, rendered: RenderedEmail) -> EmailMessage:
    """Письмо одному получателю (адреса получателей друг другу не показываются)."""
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = formataddr((config.from_name, config.from_address or ""))
    message["To"] = to
    message["Date"] = formatdate(localtime=False, usegmt=True)
    domain = (config.from_address or "localhost").rpartition("@")[2] or "localhost"
    message["Message-ID"] = make_msgid(domain=domain)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    return message
