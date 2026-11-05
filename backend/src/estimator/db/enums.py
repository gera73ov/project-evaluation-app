"""Перечисления схемы БД (contracts/db/schema.md раздел 7, правило G-7).

Типы ``ENUM`` создают миграции; модели ссылаются на них с ``create_type=False``. Значения
совпадают со строковыми перечислениями ``contracts/openapi.yaml`` — это проверяет
``tests/unit/db/test_enums.py``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class UserSource(StrEnum):
    LOCAL = "local"
    AD = "ad"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING_PASSWORD = "pending_password"  # noqa: S105  # nosec B105 — статус, не пароль
    ANONYMIZED = "anonymized"


class UserBlockReason(StrEnum):
    MANUAL = "manual"
    AD_DISABLED = "ad_disabled"
    AD_GROUP = "ad_group"
    AD_MISSING = "ad_missing"
    NOT_MATCHED = "not_matched"


class SystemRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    PRESALE = "presale"
    PRESALE_HEAD = "presale_head"
    SECURITY_AUDITOR = "security_auditor"


class RoleSource(StrEnum):
    MANUAL = "manual"
    AD_GROUP = "ad_group"


class AuthTokenKind(StrEnum):
    ACTIVATION = "activation"
    PASSWORD_RESET = "password_reset"  # noqa: S105  # nosec B105 — вид токена, не пароль


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class NodeTypeProposal(StrEnum):
    NONE = "none"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"


class CommentTagCategory(StrEnum):
    ASSUMPTION = "assumption"
    CONSTRAINT = "constraint"
    RISK = "risk"
    TECH = "tech"


class ProjectStatus(StrEnum):
    PREPARATION = "preparation"
    ESTIMATION = "estimation"
    CONSOLIDATION = "consolidation"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectOutcome(StrEnum):
    UNKNOWN = "unknown"
    WON = "won"
    LOST = "lost"
    CANCELLED = "cancelled"


class QuoteFigure(StrEnum):
    E = "e"
    P80 = "p80"
    P90 = "p90"


class DetailLevel(StrEnum):
    COARSE = "coarse"
    MEDIUM = "medium"
    DETAILED = "detailed"


class ProjectRole(StrEnum):
    MODERATOR = "moderator"
    EXPERT = "expert"
    PRESALE = "presale"


class BranchStatusValue(StrEnum):
    NOT_STARTED = "not_started"
    DRAFT = "draft"
    DONE = "done"
    NOT_NEEDED = "not_needed"


class NodeKind(StrEnum):
    PHASE = "phase"
    DISCIPLINE = "discipline"
    ITEM = "item"


class NodeAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    MOVE = "move"
    DELETE = "delete"
    RESTORE = "restore"
    SPLIT = "split"
    COLLAPSE = "collapse"
    REVIEW = "review"


class ThreadStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class CustomerQuestionStatus(StrEnum):
    NEW = "new"
    SENT = "sent"
    ANSWERED = "answered"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"


class MessageKind(StrEnum):
    MESSAGE = "message"
    EVENT = "event"
    CUSTOMER_ANSWER = "customer_answer"


class MessageHistoryReason(StrEnum):
    EDIT = "edit"
    REVOKE = "revoke"
    EDIT_AFTER_SENT = "edit_after_sent"


class AddresseeType(StrEnum):
    USER = "user"
    DISCIPLINE = "discipline"
    MODERATORS = "moderators"
    CUSTOMER = "customer"


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


class ExportStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """Тип PostgreSQL ``ENUM`` для модели: значения — ``value``, тип создаёт миграция."""
    return ENUM(
        enum_cls,
        name=name,
        values_callable=lambda cls: [m.value for m in cls],
        create_type=False,
        validate_strings=True,
    )
