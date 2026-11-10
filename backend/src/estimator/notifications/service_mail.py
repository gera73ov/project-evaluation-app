"""NTF-006 · служебные письма (FR-NOTIF-02 «Служебные письма», BR-PRJ-01, 4.5 п. 1, FR-NOTIF-03).

«Вас назначили в проект „…“» уходит письмом вместе с уведомлением ``assigned_to_project``.
Когда создаётся уведомление, решает CORE (``services.projects.lifecycle``): назначенным в
«Подготовке» — при переходе «Подготовка → Оценка», назначенным позже — в момент назначения. В
«Подготовке» уведомление не создаётся, поэтому и письма нет. Письмо служебное и не отключается
(``opt_out: null``). В нём только название проекта и ссылка, без дедлайна и подробностей
(FR-NOTIF-03).

Письма ставятся в очередь после commit (откат — письма нет) и только при настроенном SMTP.
Отправленные отмечаются ``notifications.emailed_at``. Письма о ссылках установки и сброса пароля
(``password_setup``, ``password_reset``) используют шаблоны этого же каталога
(``notifications/templates``) и ставятся из ``auth.passwords``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from estimator.db.models.users import User
from estimator.db.session import after_commit
from estimator.logging import get_logger
from estimator.notifications.mail.recipients import Recipient

log = get_logger(__name__)

#: Виды уведомлений с немедленным служебным письмом того же имени (notifications.yaml → email).
IMMEDIATE = frozenset({"assigned_to_project"})


async def on_created(db: AsyncSession, notes: Sequence[Notification]) -> int:
    """Поставить письма по созданным уведомлениям; возвращает число получателей с адресом."""
    wanted = [n for n in notes if n.kind in IMMEDIATE and n.project_id is not None]
    if not wanted:
        return 0
    from estimator.auth.passwords import base_url, smtp_configured

    if not await smtp_configured(db):
        log.info("service_mail_skipped", reason="smtp_not_configured", count=len(wanted))
        return 0
    projects = {p.id: p.name for p in (await db.scalars(
        select(Project).where(Project.id.in_({n.project_id for n in wanted}))
    )).all()}  # fmt: skip
    users = {u.id: u for u in (await db.scalars(
        select(User).where(User.id.in_({n.user_id for n in wanted}))
    )).all()}  # fmt: skip
    root = await base_url(db)
    now = dt.datetime.now(dt.UTC)
    letters: list[tuple[str, Recipient, dict[str, str]]] = []
    for note in wanted:
        user = users.get(note.user_id)
        if user is None or not user.email:
            continue
        fields = {"project_name": projects.get(note.project_id, ""),
                  "link": f"{root}/projects/{note.project_id}"}  # fmt: skip
        letters.append((note.kind, Recipient(user.email, str(user.status.value)), fields))
        note.emailed_at = now
    if not letters:
        return 0
    await db.flush()

    async def send() -> None:
        from estimator.notifications.tasks import enqueue_email

        for kind, recipient, fields in letters:
            try:
                enqueue_email(kind, [recipient], fields)
            except Exception as exc:  # noqa: BLE001 — сбой очереди не роняет назначение
                log.warning("service_mail_enqueue_failed", kind=kind, error=type(exc).__name__)

    after_commit(db, send)
    return len(letters)
