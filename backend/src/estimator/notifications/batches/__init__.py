"""NTF-004 · быстрые письма о вопросах пачкой за 15 минут (FR-NOTIF-02, Q-45, FR-NOTIF-03).

Уведомления «вопрос мне» и «ответ на мой вопрос» копятся: первое неотправленное открывает окно
:data:`WINDOW` минут, по его истечении уходит одно письмо ``questions_batch`` со всем, что
накопилось у получателя, по проектам — «Портал дилеров: 1 ответ на ваш вопрос». В письме только
название проекта, счётчики и ссылка (без названий узлов и текста). Отправленные отмечаются
``emailed_at``.

:func:`flush_due` вызывает периодическая задача раз в минуту (``notifications/tasks.py``), поэтому
письмо уходит через 15–16 минут после первого события. Письма ставятся после commit и только при
настроенном SMTP. Отключённые в профиле (``notify_questions``) и пользователи без адреса не
выбираются; их уведомления остаются без ``emailed_at`` и в окно не попадают — окно смотрит только
на последние :data:`HORIZON`. Строки уведомлений берутся ``FOR UPDATE SKIP LOCKED``: две копии
задачи не отправят одно уведомление дважды.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import UserStatus
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from estimator.db.models.users import User
from estimator.logging import get_logger
from estimator.notifications.mail.recipients import Recipient
from estimator.notifications.service_mail import Letter, queue_after_commit

log = get_logger(__name__)

KIND = "questions_batch"
QUESTION = "question_to_me"
ANSWER = "answer_to_my_question"
KINDS = (QUESTION, ANSWER)
WINDOW = dt.timedelta(minutes=15)
#: Старше этого уведомления в пачку не берутся (выключил и включил — старое не придёт).
HORIZON = dt.timedelta(days=1)


def _pending(now: dt.datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        Notification.kind.in_(KINDS),
        Notification.emailed_at.is_(None),
        Notification.project_id.is_not(None),
        Notification.created_at > now - HORIZON,
    )


async def due_users(db: AsyncSession, now: dt.datetime) -> list[uuid.UUID]:
    """Получатели, у которых окно истекло, письма включены и есть адрес."""
    first = func.min(Notification.created_at)
    stmt = (
        select(Notification.user_id)
        .join(User, User.id == Notification.user_id)
        .where(*_pending(now))
        .where(
            User.notify_questions.is_(True),
            User.email.is_not(None),
            User.status == UserStatus.ACTIVE,
        )
        .group_by(Notification.user_id)
        .having(first <= now - WINDOW)
    )
    return list((await db.scalars(stmt)).all())


async def flush_due(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Собрать пачки, у которых истекло окно; вернуть число писем."""
    now = now or dt.datetime.now(dt.UTC)
    users = await due_users(db, now)
    if not users:
        return 0
    from estimator.auth.passwords import base_url, smtp_configured

    if not await smtp_configured(db):
        log.info("questions_batch_skipped", reason="smtp_not_configured", users=len(users))
        return 0
    notes = (await db.scalars(
        select(Notification).where(*_pending(now), Notification.user_id.in_(users))
        .order_by(Notification.created_at, Notification.id)
        .with_for_update(skip_locked=True)
    )).all()  # fmt: skip
    people = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(users)))).all()}
    names = dict((await db.execute(
        select(Project.id, Project.name).where(Project.id.in_({n.project_id for n in notes}))
    )).all())  # fmt: skip
    root = await base_url(db)
    counts: dict[uuid.UUID, dict[uuid.UUID, dict[str, int]]] = defaultdict(dict)
    for note in notes:
        assert note.project_id is not None  # noqa: S101 — отобрано условием _pending
        per = counts[note.user_id].setdefault(note.project_id, {QUESTION: 0, ANSWER: 0})
        per[note.kind] += 1
        note.emailed_at = now
    letters: list[Letter] = []
    for user_id, projects in counts.items():
        user = people[user_id]
        items = [
            {"project_name": names.get(pid, ""), "questions": c[QUESTION], "answers": c[ANSWER],
             "link": f"{root}/projects/{pid}"}
            for pid, c in projects.items()
        ]  # fmt: skip
        letters.append((KIND, Recipient(str(user.email), user.status.value), {"projects": items}))
    await db.flush()
    queue_after_commit(db, letters)
    log.info("questions_batch_queued", letters=len(letters), notifications=len(notes))
    return len(letters)
