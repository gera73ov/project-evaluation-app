"""Почта (NTF-002): параметры SMTP, шаблоны, отправка задачей Celery.

* :func:`estimator.notifications.tasks.enqueue_email` — поставить письма в очередь
  (получатели фильтруются по :mod:`.recipients`, одно письмо на адрес);
* :func:`send_test_email` — «Отправить тестовое письмо» мастера настройки (7.1 шаг 2):
  синхронно, с параметрами из формы, до сохранения;
* для оповещения ИБ при смене SMTP (SEC-011) задаче передаются параметры *старого* сервера
  (``smtp_override``), пароль — в зашифрованном виде, как в ``system_settings``.
"""

from __future__ import annotations

from estimator.notifications.mail.config import SmtpConfig
from estimator.notifications.mail.recipients import Recipient, can_receive, deliverable
from estimator.notifications.mail.render import (
    EMAIL_FIELDS,
    TEST_EMAIL,
    RenderedEmail,
    build_message,
    render_email,
)
from estimator.notifications.mail.sender import SmtpNotConfiguredError, send_message

__all__ = [
    "EMAIL_FIELDS",
    "Recipient",
    "RenderedEmail",
    "SmtpConfig",
    "SmtpNotConfiguredError",
    "build_message",
    "can_receive",
    "deliverable",
    "render_email",
    "send_message",
    "send_test_email",
]


def send_test_email(config: SmtpConfig, to: str, app_link: str) -> None:
    """Отправить тестовое письмо сразу (ошибка SMTP пробрасывается в мастер настройки)."""
    send_message(config, build_message(config, to, render_email(TEST_EMAIL, {"link": app_link})))
