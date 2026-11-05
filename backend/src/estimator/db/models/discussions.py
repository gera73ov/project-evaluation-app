"""Обсуждения, вопросы заказчику, адресаты, заметки модераторов, уведомления
(DB-007; contracts/db/schema.md 2.5).

``message_history`` — только INSERT для роли приложения (G-5): права отзывает миграция
``0008_discussions``. Заметки (``project_notes``) читают и пишут только с правами
``notes.read`` / ``notes.write`` (SEC-AUTHZ-04); в снимки и экспорт они не попадают (FR-NOTE-01).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.enums import (
    AddresseeType,
    CustomerQuestionStatus,
    MessageHistoryReason,
    MessageKind,
    ThreadStatus,
    pg_enum,
)
from estimator.db.models.projects import project_fk, user_fk

_FALSE = text("false")
_NOW = text("now()")


def node_fk(ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey("nodes.id", ondelete=ondelete)


class Thread(UUIDPrimaryKey, AuditColumns, Base):
    """Обсуждение узла или проекта; вопрос заказчику — ``is_customer`` (FR-DISC-09, BR-CQ-02)."""

    __tablename__ = "threads"
    __table_args__ = (
        CheckConstraint(
            "is_customer = (customer_question_no IS NOT NULL)", name="customer_question_no"
        ),
        CheckConstraint("is_customer = (customer_status IS NOT NULL)", name="customer_status"),
        CheckConstraint(
            "customer_status IS DISTINCT FROM 'withdrawn' OR withdraw_reason IS NOT NULL",
            name="withdraw_reason",
        ),
        Index("threads_project_open_idx", "project_id", postgresql_where=text("status = 'open'")),
        Index(
            "threads_customer_question_no",
            "project_id",
            "customer_question_no",
            unique=True,
            postgresql_where=text("is_customer"),
        ),
        Index("threads_node_id_idx", "node_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    node_id: Mapped[uuid.UUID | None] = mapped_column(node_fk())
    opened_by: Mapped[uuid.UUID] = mapped_column(user_fk())
    status: Mapped[ThreadStatus] = mapped_column(
        pg_enum(ThreadStatus, "thread_status"), server_default=ThreadStatus.OPEN.value
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    resolved_at: Mapped[dt.datetime | None]
    is_customer: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    customer_question_no: Mapped[int | None] = mapped_column(Integer)
    customer_status: Mapped[CustomerQuestionStatus | None] = mapped_column(
        pg_enum(CustomerQuestionStatus, "customer_question_status")
    )
    sent_at: Mapped[dt.datetime | None]
    answered_at: Mapped[dt.datetime | None]
    closed_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    closed_at: Mapped[dt.datetime | None]
    withdraw_reason: Mapped[str | None] = mapped_column(String(500))
    edited_after_sent: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)


class Message(UUIDPrimaryKey, Base):
    """Сообщение ленты: обычное (до 4 000), событие или ответ заказчика (до 10 000, FR-DISC-02)."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("kind = 'event' OR char_length(body) >= 1", name="body_min"),
        CheckConstraint("kind = 'customer_answer' OR char_length(body) <= 4000", name="body_max"),
        CheckConstraint("(kind = 'event') = (event IS NOT NULL)", name="event"),
        Index("messages_node_id_created_at_idx", "node_id", "created_at"),
        Index("messages_thread_id_created_at_idx", "thread_id", "created_at"),
        Index(
            "messages_project_feed_idx",
            "project_id",
            "created_at",
            postgresql_where=text("node_id IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    node_id: Mapped[uuid.UUID | None] = mapped_column(node_fk())
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    body: Mapped[str] = mapped_column(String(10000))
    kind: Mapped[MessageKind] = mapped_column(
        pg_enum(MessageKind, "message_kind"), server_default=MessageKind.MESSAGE.value
    )
    event: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    needs_answer: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    edited_at: Mapped[dt.datetime | None]
    edited_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    revoked_at: Mapped[dt.datetime | None]


class MessageHistory(UUIDPrimaryKey, Base):
    """Текст сообщения до правки или отзыва; только INSERT (G-5)."""

    __tablename__ = "message_history"
    __table_args__ = (Index("message_history_message_id_edited_at_idx", "message_id", "edited_at"),)

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(String(10000))
    edited_by: Mapped[uuid.UUID] = mapped_column(user_fk())
    edited_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    reason: Mapped[MessageHistoryReason] = mapped_column(
        pg_enum(MessageHistoryReason, "message_history_reason")
    )


class MessageAddressee(Base):
    """Адресат сообщения: пользователь, дисциплина, модераторы или заказчик.

    Первичного ключа в таблице нет (contracts/db/schema.md 2.5): строку определяет
    ``UNIQUE NULLS NOT DISTINCT (message_id, target_type, target_id)``; ORM берёт эти столбцы
    ключом отображения.
    """

    __tablename__ = "message_addressees"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "target_type", "target_id", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint(
            "(target_type IN ('user', 'discipline')) = (target_id IS NOT NULL)", name="target"
        ),
        Index("message_addressees_target_type_target_id_idx", "target_type", "target_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    target_type: Mapped[AddresseeType] = mapped_column(pg_enum(AddresseeType, "addressee_type"))
    target_id: Mapped[uuid.UUID | None] = mapped_column()

    __mapper_args__ = {"primary_key": [message_id, target_type, target_id]}  # noqa: RUF012


class ProjectNote(UUIDPrimaryKey, AuditColumns, Base):
    """Заметка модераторов (FR-NOTE-01); доступ только с ``notes.read`` / ``notes.write``."""

    __tablename__ = "project_notes"
    __table_args__ = (
        CheckConstraint("char_length(body) >= 1", name="body"),
        Index(
            "project_notes_project_id_node_id_created_at_idx", "project_id", "node_id", "created_at"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    node_id: Mapped[uuid.UUID | None] = mapped_column(node_fk())
    author_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    body: Mapped[str] = mapped_column(String(4000))
    edited_at: Mapped[dt.datetime | None]


class Notification(UUIDPrimaryKey, Base):
    """Уведомление в колокольчике; вид — из ``contracts/notifications.yaml`` (DB-D06), без денег."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("notifications_unread_idx", "user_id", postgresql_where=text("read_at IS NULL")),
        Index("notifications_user_id_created_at_idx", "user_id", text("created_at DESC")),
        Index("notifications_created_at_idx", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    project_id: Mapped[uuid.UUID | None] = mapped_column(project_fk())
    node_id: Mapped[uuid.UUID | None] = mapped_column(node_fk("SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_NOW)
    read_at: Mapped[dt.datetime | None]
    emailed_at: Mapped[dt.datetime | None]
