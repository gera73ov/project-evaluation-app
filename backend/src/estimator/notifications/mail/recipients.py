"""Кому можно отправить письмо (NTF-002; contracts/notifications.yaml, правила N-*).

* N-NO-EMAIL — пользователю без email письма не отправляются;
* N-BLOCKED — заблокированный (и обезличенный) не получает писем, пользователь в
  ``pending_password`` — только письмо установки пароля.

Отключения писем в профиле (``notify_digest``, ``notify_questions``) учитывают сборщики
сводки и пачек (NTF-003, NTF-004) до вызова отправки.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Recipient:
    email: str | None
    status: str  # user_status: active, blocked, pending_password, anonymized


def can_receive(kind: str, recipient: Recipient) -> bool:
    if not recipient.email:
        return False
    if recipient.status == "active":
        return True
    return recipient.status == "pending_password" and kind == "password_setup"


def deliverable(kind: str, recipients: Iterable[Recipient]) -> list[str]:
    """Адреса, которым можно отправить письмо ``kind``, без повторов (порядок сохраняется)."""
    seen: dict[str, None] = {}
    for recipient in recipients:
        if can_receive(kind, recipient) and recipient.email:
            seen.setdefault(recipient.email.strip(), None)
    return list(seen)
