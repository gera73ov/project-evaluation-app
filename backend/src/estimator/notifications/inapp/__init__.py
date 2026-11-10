"""NTF-003 · уведомления в приложении (SPEC FR-NOTIF-01, 3.4 строки 15–16, 14.2
``notifications``, 15.2 ``GET /notifications``, ``POST /notifications/read``, 15.4
``notification.created``, 11.3 №5–6).

:func:`notify` — единая точка для CORE, ADM и AUTH: вид из каталога NTF-001 (:data:`KINDS`,
сверяется с contracts/notifications.yaml тестом), гейт по статусу проекта (класс вида), правила
N-AUTHOR, N-BLOCKED, N-MEMBERSHIP. Каждому получателю после ``COMMIT`` уходит событие
``notification.created`` в канал ``user:{id}`` с числом непрочитанных. ``read_at`` — источник
метрики пилота «доля увиденных правок» (1.3).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectRole, ProjectStatus, UserStatus
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User
from estimator.db.uuid7 import uuid7
from estimator.realtime.bus import publish


@dataclass(frozen=True)
class Kind:
    """Вид уведомления: класс (гейт по статусу), связь с вопросами заказчику, хранение."""

    cls: str  # estimation | service | security
    cq_related: bool = False
    store: bool = True
    #: получатели не обязаны быть участниками проекта (project_without_moderator — администраторы)
    outside_project: bool = False


#: Каталог видов (contracts/notifications.yaml, раздел 3).
KINDS: Mapping[str, Kind] = {
    "question_to_me": Kind("estimation"),
    "answer_to_my_question": Kind("estimation", cq_related=True),
    "moderator_change": Kind("estimation"),
    "branch_back_to_draft": Kind("estimation"),
    "assigned_to_project": Kind("service"),
    "member_replaced": Kind("service"),
    "question_redirected": Kind("service"),
    "member_blocked": Kind("service"),
    "presale_head_joined": Kind("service"),
    "support_session_opened": Kind("security"),
    "project_without_moderator": Kind("service", outside_project=True),
    "cell_taken_over": Kind("service", store=False),
}

#: Статусы проекта по классам (раздел 1 каталога): allow / deny / customer_questions_only.
CLASS_STATUSES: Mapping[str, Mapping[str, str]] = {
    "estimation": {
        "preparation": "deny",
        "estimation": "allow",
        "consolidation": "allow",
        "completed": "customer_questions_only",
        "archived": "deny",
    },
    "service": dict.fromkeys(
        ("preparation", "estimation", "consolidation", "completed", "archived"), "allow"
    ),
    "security": dict.fromkeys(
        ("preparation", "estimation", "consolidation", "completed", "archived"), "allow"
    ),
}


class UnknownKindError(ValueError):
    """Вида нет в каталоге NTF-001."""


def status_allows(kind: str, project_status: str | None) -> bool:
    """Создаётся ли уведомление вида ``kind`` при статусе проекта (M3.4-15/16)."""
    spec = KINDS.get(kind)
    if spec is None:
        raise UnknownKindError(kind)
    if project_status is None:
        return True
    rule = CLASS_STATUSES[spec.cls][project_status]
    if rule == "customer_questions_only":
        return spec.cq_related
    return rule == "allow"


def _ts(value: dt.datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def notification_out(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "project_id": str(n.project_id) if n.project_id else None,
        "node_id": str(n.node_id) if n.node_id else None,
        "payload": dict(n.payload),
        "created_at": _ts(n.created_at),
        "read_at": _ts(n.read_at),
    }


async def _eligible(
    db: AsyncSession,
    kind: Kind,
    recipients: set[uuid.UUID],
    project_id: uuid.UUID | None,
    project_status: str | None,
) -> list[uuid.UUID]:
    """N-BLOCKED: только активные; N-MEMBERSHIP: участник, которому проект виден по статусу."""
    stmt = select(User.id).where(User.id.in_(recipients), User.status == UserStatus.ACTIVE)
    if project_id is not None and not kind.outside_project:
        members = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        if project_status == ProjectStatus.PREPARATION.value:
            members = members.where(ProjectMember.role == ProjectRole.MODERATOR)
        stmt = stmt.where(User.id.in_(members))
    return sorted((await db.scalars(stmt)).all())


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    return int(await db.scalar(stmt) or 0)


async def unread_by_project(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Счётчик «Мне» по проектам (11.3 №5, CORE-033)."""
    rows = await db.execute(
        select(Notification.project_id, func.count())
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.project_id.is_not(None),
        )
        .group_by(Notification.project_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


async def notify(
    db: AsyncSession,
    kind: str,
    recipients: Iterable[uuid.UUID],
    *,
    project_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    payload: Mapping[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
) -> list[Notification]:
    """Создать уведомления вида ``kind``; возвращает созданные строки (пусто — гейт закрыт)."""
    spec = KINDS.get(kind)
    if spec is None:
        raise UnknownKindError(kind)
    status: str | None = None
    if project_id is not None:
        raw = await db.scalar(select(Project.status).where(Project.id == project_id))
        if raw is None:
            return []
        status = str(raw)
    if not status_allows(kind, status):
        return []
    wanted = set(recipients) - ({actor_id} if actor_id else set())  # N-AUTHOR
    if not wanted:
        return []
    users = await _eligible(db, spec, wanted, project_id, status)
    body = dict(payload or {})
    created: list[Notification] = []
    now = dt.datetime.now(dt.UTC)
    for user_id in users:
        note = Notification(
            id=uuid7(),
            user_id=user_id,
            project_id=project_id,
            node_id=node_id,
            kind=kind,
            payload=body,
            created_at=now,
        )
        if spec.store:
            db.add(note)
        created.append(note)
    if spec.store:
        await db.flush()
    for note in created:
        unread = await unread_count(db, note.user_id) if spec.store else 0
        out = notification_out(note)
        out.pop("read_at")
        publish(
            db,
            f"user:{note.user_id}",
            "notification.created",
            {"notification": out, "unread_count": unread},
        )
    from estimator.notifications import service_mail

    if created and kind in service_mail.IMMEDIATE:
        await service_mail.on_created(db, created)  # письмо «Вас назначили» (NTF-006)
    return created


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    after_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Notification]:
    """Новые сверху; ``limit + 1`` строк для признака следующей страницы."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if after_id is not None:
        stmt = stmt.where(Notification.id < after_id)
    stmt = stmt.order_by(Notification.id.desc()).limit(limit + 1)
    return list((await db.scalars(stmt)).all())


async def mark_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ids: Sequence[uuid.UUID] = (),
    all_: bool = False,
) -> int:
    """Отметить прочитанными (свои уведомления; чужие id молча пропускаются)."""
    if not all_ and not ids:
        return 0
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=dt.datetime.now(dt.UTC))
        .execution_options(synchronize_session=False)
    )
    if not all_:
        stmt = stmt.where(Notification.id.in_(list(ids)))
    result = await db.execute(stmt)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
