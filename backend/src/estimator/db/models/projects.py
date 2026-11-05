"""Проекты, команда, фазы и дисциплины проекта, статусы веток, режим поддержки
(DB-005; contracts/db/schema.md 2.3).

Деньги здесь не живут: ставки, валюта, НДС, сумма договора и кэш итогов — в
:mod:`estimator.db.models.money`, импорт которого разрешён только сервису денег (G-11).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from estimator.db.base import AuditColumns, Base, UUIDPrimaryKey
from estimator.db.enums import (
    BranchStatusValue,
    DetailLevel,
    ProjectOutcome,
    ProjectRole,
    ProjectStatus,
    QuoteFigure,
    pg_enum,
)

_FALSE = text("false")
_TRUE = text("true")


def project_fk() -> ForeignKey:
    """Ключ на проект с каскадом — для ``estimator project purge`` (G-12, BR-PRJ-04)."""
    return ForeignKey("projects.id", ondelete="CASCADE")


def user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="RESTRICT")


class Project(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 3", name="name_length"),
        CheckConstraint("char_length(customer) >= 1", name="customer_length"),
        CheckConstraint("next_question_no >= 1", name="next_question_no"),
        CheckConstraint("outcome = 'lost' OR loss_reason_id IS NULL", name="loss_reason"),
        CheckConstraint("duration_weeks BETWEEN 1 AND 260", name="duration_weeks"),
        CheckConstraint(
            "pm_percent BETWEEN 0 AND 50 AND pm_percent * 2 = trunc(pm_percent * 2)",
            name="pm_percent",
        ),
        CheckConstraint(
            "cancel_reason IS NULL OR char_length(cancel_reason) >= 10", name="cancel_reason"
        ),
        Index("projects_status_idx", "status"),
        Index(
            "projects_no_moderator_idx",
            "no_moderator_since",
            postgresql_where=text("no_moderator_since IS NOT NULL"),
        ),
        Index(
            "projects_completed_idx",
            "completed_at",
            postgresql_where=text("status = 'completed'"),
        ),
        Index("projects_created_at_idx", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(200))
    customer: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(10000), server_default=text("''"))
    next_question_no: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus, "project_status"), server_default=ProjectStatus.PREPARATION.value
    )
    outcome: Mapped[ProjectOutcome] = mapped_column(
        pg_enum(ProjectOutcome, "project_outcome"), server_default=ProjectOutcome.UNKNOWN.value
    )
    loss_reason_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("loss_reasons.id", ondelete="RESTRICT")
    )
    loss_reason_text: Mapped[str | None] = mapped_column(String(500))
    quote_figure: Mapped[QuoteFigure] = mapped_column(
        pg_enum(QuoteFigure, "quote_figure"), server_default=QuoteFigure.P80.value
    )
    duration_weeks: Mapped[int | None] = mapped_column(SmallInteger)
    no_moderator_since: Mapped[dt.datetime | None]
    detail_level: Mapped[DetailLevel] = mapped_column(
        pg_enum(DetailLevel, "detail_level"), server_default=DetailLevel.MEDIUM.value
    )
    pm_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    pm_percent_reason: Mapped[str] = mapped_column(String(1000), server_default=text("''"))
    deadline: Mapped[dt.date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    completed_at: Mapped[dt.datetime | None]
    archived_at: Mapped[dt.datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )


class ProjectMember(UUIDPrimaryKey, AuditColumns, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "role", "discipline_id", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint("(role = 'expert') = (discipline_id IS NOT NULL)", name="discipline"),
        CheckConstraint("NOT is_reviewer OR role = 'expert'", name="reviewer"),
        Index("project_members_user_id_idx", "user_id"),
        Index("project_members_project_id_role_idx", "project_id", "role"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    user_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    role: Mapped[ProjectRole] = mapped_column(pg_enum(ProjectRole, "project_role"))
    discipline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    is_reviewer: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    added_by_admin_self: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    notified_at: Mapped[dt.datetime | None]


class ProjectPhase(Base):
    __tablename__ = "project_phases"
    __table_args__ = (PrimaryKeyConstraint("project_id", "phase_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    phase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)
    in_pm_base: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)


class ProjectDiscipline(AuditColumns, Base):
    __tablename__ = "project_disciplines"
    __table_args__ = (PrimaryKeyConstraint("project_id", "discipline_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    discipline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discipline_profiles.id", ondelete="RESTRICT")
    )


class BranchStatus(Base):
    """Статус пары «фаза × дисциплина» — ровно один (BR-BR-03)."""

    __tablename__ = "branch_status"
    __table_args__ = (PrimaryKeyConstraint("project_id", "phase_id", "discipline_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    phase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"))
    discipline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disciplines.id", ondelete="RESTRICT")
    )
    status: Mapped[BranchStatusValue] = mapped_column(
        pg_enum(BranchStatusValue, "branch_status_value"),
        server_default=BranchStatusValue.NOT_STARTED.value,
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(user_fk())
    changed_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class SupportSession(UUIDPrimaryKey, Base):
    """Режим поддержки администратора, не дольше 60 минут (FR-ADM-06)."""

    __tablename__ = "support_sessions"
    __table_args__ = (
        CheckConstraint("char_length(reason) >= 10", name="reason"),
        CheckConstraint("expires_at <= started_at + interval '60 minutes'", name="expires"),
        Index("support_sessions_admin_project_idx", "admin_id", "project_id", "expires_at"),
    )

    admin_id: Mapped[uuid.UUID] = mapped_column(user_fk())
    project_id: Mapped[uuid.UUID] = mapped_column(project_fk())
    reason: Mapped[str] = mapped_column(String(500))
    started_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    expires_at: Mapped[dt.datetime]
    ended_at: Mapped[dt.datetime | None]
