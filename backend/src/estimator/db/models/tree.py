"""Дерево оценки, история узлов, лог изменений, состояние вида, журнал проекта
(DB-006; contracts/db/schema.md 2.4 и 3).

``node_history`` и ``project_journal`` — только INSERT для роли приложения (G-5): права
отзывает миграция ``0007_tree``. Десятичные значения внутри JSONB — строками (G-9).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.enums import NodeAction, NodeKind, pg_enum
from estimator.db.models.projects import project_fk, user_fk

_HOURS = Numeric(10, 2)


def _hours_check(column: str) -> CheckConstraint:
    # BR-CALC-03: 0–99 999,5 с шагом 0,5
    return CheckConstraint(
        f"{column} IS NULL OR "
        f"({column} BETWEEN 0 AND 99999.5 AND {column} * 2 = trunc({column} * 2))",
        name=column,
    )


class Node(UUIDPrimaryKey, AuditColumns, Base):
    """Узел дерева: фаза, ветка дисциплины или элемент работ (ARCH-04, 14.2)."""

    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint("char_length(title) >= 1 AND title !~ '[\\r\\n]'", name="title"),
        _hours_check("o"),
        _hours_check("r"),
        _hours_check("p"),
        CheckConstraint("multiplier BETWEEN 1 AND 10000", name="multiplier"),
        CheckConstraint(
            "comment_lines IS NULL OR jsonb_typeof(comment_lines) = 'array'", name="comment_lines"
        ),
        CheckConstraint("(reviewed_by IS NULL) = (reviewed_at IS NULL)", name="reviewed"),
        CheckConstraint("NOT self_review OR reviewed_by IS NOT NULL", name="self_review"),
        CheckConstraint("(deleted_at IS NULL) = (deleted_batch_id IS NULL)", name="deleted"),
        CheckConstraint(
            "kind <> 'item' OR (phase_id IS NOT NULL AND discipline_id IS NOT NULL)",
            name="item_branch",
        ),
        CheckConstraint("(kind = 'phase') = (parent_id IS NULL)", name="root"),
        CheckConstraint(
            "kind <> 'phase' OR (discipline_id IS NULL AND o IS NULL AND r IS NULL AND p IS NULL)",
            name="phase_kind",
        ),
        CheckConstraint(
            "kind <> 'discipline' OR discipline_id IS NOT NULL", name="discipline_kind"
        ),
        CheckConstraint("kind = 'item' OR type_id IS NULL", name="type"),
        Index("nodes_project_live_idx", "project_id", postgresql_where=text("deleted_at IS NULL")),
        Index("nodes_parent_position_idx", "parent_id", "position"),
        Index(
            "nodes_batch_idx",
            "project_id",
            "deleted_batch_id",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        Index(
            "nodes_one_phase",
            "project_id",
            "phase_id",
            unique=True,
            postgresql_where=text("kind = 'phase' AND deleted_at IS NULL"),
        ),
        Index(
            "nodes_one_branch",
            "project_id",
            "phase_id",
            "discipline_id",
            unique=True,
            postgresql_where=text("kind = 'discipline' AND deleted_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    kind: Mapped[NodeKind] = mapped_column(pg_enum(NodeKind, "node_kind"))
    phase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"))
    discipline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    # NO ACTION, не RESTRICT: локальный тип и его узлы удаляются одним каскадом от проекта
    type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("node_types.id"))
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(Text(collation="C"))
    o: Mapped[Decimal | None] = mapped_column(_HOURS)
    r: Mapped[Decimal | None] = mapped_column(_HOURS)
    p: Mapped[Decimal | None] = mapped_column(_HOURS)
    multiplier: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    comment_lines: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    reviewed_at: Mapped[dt.datetime | None]
    self_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    deleted_at: Mapped[dt.datetime | None]
    deleted_batch_id: Mapped[uuid.UUID | None]
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())


class NodeHistory(UUIDPrimaryKey, Base):
    """История изменений узла; только INSERT (G-5, FR-TREE-25)."""

    __tablename__ = "node_history"
    __table_args__ = (
        Index("node_history_node_id_created_at_idx", "node_id", "created_at"),
        Index(
            "node_history_project_id_user_id_created_at_idx", "project_id", "user_id", "created_at"
        ),
    )

    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    project_version: Mapped[int] = mapped_column(BigInteger)
    node_version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    action: Mapped[NodeAction] = mapped_column(pg_enum(NodeAction, "node_action"))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class ChangeLog(Base):
    """События проекта по версиям для догона после переподключения (ARCH-02); без денег."""

    __tablename__ = "change_log"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "version"),
        Index("change_log_created_at_idx", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    version: Mapped[int] = mapped_column(BigInteger)
    event: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class UserViewState(Base):
    """Раскрытие, фильтры и ширины колонок пользователя в проекте."""

    __tablename__ = "user_view_state"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_id"),
        Index("user_view_state_project_id_idx", "project_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class ProjectJournal(UUIDPrimaryKey, Base):
    """Журнал проекта (CORE-032, GAP-02); только INSERT (G-5). Денежные записи — ``is_money``."""

    __tablename__ = "project_journal"
    __table_args__ = (
        CheckConstraint(
            "is_money OR NOT (changes ?| array['rate_rub', 'exchange_rate', 'vat_percent', "
            "'contract_amount', 'currency'])",
            name="money_keys",
        ),
        Index("project_journal_project_id_id_idx", "project_id", text("id DESC")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    user_id: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    action: Mapped[str] = mapped_column(Text)
    is_money: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
