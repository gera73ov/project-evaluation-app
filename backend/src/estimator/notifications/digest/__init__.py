"""NTF-005 · ежедневная сводка (FR-NOTIF-02 «Ежедневная сводка», ``digest.time``, FR-UI-02).

Раз в день в ``digest.time`` (по умолчанию 09:00, часовой пояс приложения) — письмо ``digest``
со счётчиками новых уведомлений класса «оценка» по проектам («Сводка: 3 новых события в
2 проектах»). Письмо уходит, только если с прошлой сводки (``users.last_digest_at``) появились
новые уведомления; для того, кто сводку ещё не получал, считаются последние сутки. Отключается в
профиле (``notify_digest``). В письме только название проекта, счётчики и ссылка (FR-NOTIF-03).

:func:`send_due` вызывает периодическая задача каждые 5 минут: настройку времени можно менять без
перезапуска beat, а пропущенная из-за остановки worker сводка уходит при следующем запуске. Кто
уже получил сводку после сегодняшнего ``digest.time``, второй раз её не получит.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import UserStatus
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project
from estimator.db.models.users import User
from estimator.logging import get_logger
from estimator.notifications.inapp import KINDS as NOTIFICATION_KINDS
from estimator.notifications.mail.recipients import Recipient
from estimator.notifications.service_mail import Letter, queue_after_commit

log = get_logger(__name__)

KIND = "digest"
SETTING = "digest.time"
DEFAULT_TIME = "09:00"
#: Виды класса «оценка» (contracts/notifications.yaml, digest.condition).
KINDS = tuple(sorted(k for k, spec in NOTIFICATION_KINDS.items() if spec.cls == "estimation"))
FIRST_LOOKBACK = dt.timedelta(days=1)


async def slot(db: AsyncSession, now: dt.datetime) -> dt.datetime:
    """Момент сегодняшней сводки (``digest.time`` в поясе приложения), в UTC."""
    from estimator.auth.policy import read_settings
    from estimator.services.common import app_timezone

    raw = (await read_settings(db, SETTING)).get(SETTING) or DEFAULT_TIME
    try:
        hour, minute = (int(part) for part in str(raw).split(":"))
        at = dt.time(hour, minute)
    except ValueError:
        at = dt.time(9, 0)
    zone = await app_timezone(db)
    local = now.astimezone(zone)
    return dt.datetime.combine(local.date(), at, tzinfo=zone).astimezone(dt.UTC)


async def send_due(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Отправить сводки, время которых наступило; вернуть число писем."""
    now = now or dt.datetime.now(dt.UTC)
    today = await slot(db, now)
    if now < today:
        return 0
    since = func.coalesce(User.last_digest_at, today - FIRST_LOOKBACK)
    rows = (await db.execute(
        select(Notification.user_id, Notification.project_id, Notification.kind, func.count())
        .join(User, User.id == Notification.user_id)
        .where(
            User.notify_digest.is_(True), User.email.is_not(None),
            User.status == UserStatus.ACTIVE,
            (User.last_digest_at.is_(None)) | (User.last_digest_at < today),
            Notification.kind.in_(KINDS), Notification.project_id.is_not(None),
            Notification.created_at > since, Notification.created_at <= now,
        )
        .group_by(Notification.user_id, Notification.project_id, Notification.kind)
    )).all()  # fmt: skip
    if not rows:
        return 0
    from estimator.auth.passwords import base_url, smtp_configured

    if not await smtp_configured(db):
        log.info("digest_skipped", reason="smtp_not_configured")
        return 0
    counters: dict[uuid.UUID, dict[uuid.UUID, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for user_id, project_id, kind, count in rows:
        if project_id is None:  # отобрано условием запроса, проверка для типов
            continue
        counters[user_id][project_id][kind] = int(count)
    users = {u.id: u for u in (await db.scalars(
        select(User).where(User.id.in_(counters)).with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )).all()}  # fmt: skip
    project_ids = {pid for per in counters.values() for pid in per}
    names = dict((await db.execute(
        select(Project.id, Project.name).where(Project.id.in_(project_ids))
    )).all())  # fmt: skip
    root = await base_url(db)
    letters: list[Letter] = []
    for user_id, projects in counters.items():
        user = users.get(user_id)
        # строку держит другая транзакция или она уже отправила сводку — пропускаем
        if user is None or (user.last_digest_at is not None and user.last_digest_at >= today):
            continue
        items = sorted(
            ({"project_name": names.get(pid, ""), "counters": dict(c),
              "link": f"{root}/projects/{pid}"} for pid, c in projects.items()),
            key=lambda item: str(item["project_name"]),
        )  # fmt: skip
        total = sum(sum(c.values()) for c in projects.values())
        letters.append((KIND, Recipient(str(user.email), user.status.value),
                        {"projects": items, "total": total}))  # fmt: skip
        user.last_digest_at = now
    await db.flush()
    queue_after_commit(db, letters)
    log.info("digest_queued", letters=len(letters))
    return len(letters)
