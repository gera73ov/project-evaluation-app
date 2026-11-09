"""Схемы запросов и ответов CORE/ADM/NTF этапа 2 (contracts/openapi.yaml; API-004).

Схемы повторяют компоненты контракта один в один: ``tests/contract/test_openapi_implementation``
сравнивает их с контрактом, а живые ответы API-тестов сверяются с ним хуком ``check_response``.
Десятичные значения — строками (``DecimalString``, ``HoursString``), время — строками ISO 8601.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.common.decimal import DecimalString
from estimator.db.enums import (
    BranchStatusValue,
    DetailLevel,
    ProjectOutcome,
    ProjectRole,
    ProjectStatus,
    QuoteFigure,
    SystemRole,
)
from estimator.services.tree.local_types import NodeTypeIcon


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- общее ------------------------------------------------------------------------------------


class UserRef(_Strict):
    id: uuid.UUID
    full_name: str = Field(max_length=200)
    initials: str = Field(max_length=4)
    is_active: bool = Field(default=None)  # type: ignore[assignment]
    color: str = Field(default=None)  # type: ignore[assignment]


# --- проект -----------------------------------------------------------------------------------


class ProjectCreate(_Strict):
    name: str = Field(min_length=3, max_length=200)
    customer: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    phase_ids: list[uuid.UUID] = Field(min_length=1)
    detail_level: DetailLevel = DetailLevel.MEDIUM
    deadline: dt.date | None = None


class PhasePatch(_Strict):
    phase_id: uuid.UUID
    is_enabled: bool | None = None
    in_pm_base: bool | None = None


class ProjectPatch(_Strict):
    name: str = Field(default=None, min_length=3, max_length=200)  # type: ignore[assignment]
    customer: str = Field(default=None, min_length=1, max_length=200)  # type: ignore[assignment]
    description: str = Field(default=None, max_length=10000)  # type: ignore[assignment]
    detail_level: DetailLevel = Field(default=None)  # type: ignore[assignment]
    pm_percent: DecimalString = Field(default=None)  # type: ignore[assignment]
    pm_percent_reason: str = Field(default=None, max_length=1000)  # type: ignore[assignment]
    quote_figure: QuoteFigure = Field(default=None)  # type: ignore[assignment]
    duration_weeks: int | None = Field(default=None, ge=1, le=260)
    deadline: dt.date | None = None
    phases: list[PhasePatch] = Field(default=None)  # type: ignore[assignment]
    confirm: bool = False


class ProjectPhaseOut(_Strict):
    phase_id: uuid.UUID
    name: str
    is_cross_cutting: bool
    is_enabled: bool
    in_pm_base: bool


class ProjectDisciplineOut(_Strict):
    discipline_id: uuid.UUID
    name: str
    profile_id: uuid.UUID
    has_expert: bool


class ProjectOut(_Strict):
    id: uuid.UUID
    name: str
    customer: str
    description: str
    status: ProjectStatus
    outcome: ProjectOutcome
    detail_level: DetailLevel
    pm_percent: str
    pm_percent_reason: str
    quote_figure: QuoteFigure
    duration_weeks: int | None = Field(ge=1, le=260)
    deadline: dt.date | None
    version: int
    phases: list[ProjectPhaseOut]
    disciplines: list[ProjectDisciplineOut]
    completed_at: str | None = None
    archived_at: str | None = None
    cancel_reason: str | None = None
    created_at: str
    access: Literal["member", "presale_head", "support"]
    my_permissions: list[str]
    support_expires_at: str | None = None


class ProjectVersioned(_Strict):
    project: ProjectOut
    project_version: int


# --- дерево -----------------------------------------------------------------------------------


class CommentLine(_Strict):
    tag_id: uuid.UUID | None
    text: str = Field(max_length=2000)


class NodeOut(_Strict):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: Literal["phase", "discipline", "item"]
    phase_id: uuid.UUID
    discipline_id: uuid.UUID | None
    type_id: uuid.UUID | None
    title: str = Field(max_length=200)
    position: str
    o: str | None
    r: str | None
    p: str | None
    multiplier: int = Field(ge=1, le=10000)
    comment_lines: list[CommentLine] | None = Field(max_length=10)
    reviewed_by: UserRef | None = None
    reviewed_at: str | None = None
    self_review: bool = Field(default=None)  # type: ignore[assignment]
    version: int
    field_versions: dict[str, Any] = Field(default=None)  # type: ignore[assignment]
    e: str | None
    sigma: str | None
    p80: str | None = None
    p90: str | None = None
    sum_o: str | None = None
    sum_r: str | None = None
    sum_p: str | None = None
    leaf_state: Literal["valid", "zero", "empty", "invalid"] | None = None
    is_large: bool = Field(default=None)  # type: ignore[assignment]
    is_repeating: bool = Field(default=None)  # type: ignore[assignment]
    unaccounted_leaves: int = Field(default=None)  # type: ignore[assignment]
    messages_count: int = Field(default=None)  # type: ignore[assignment]
    open_questions: int = Field(default=None)  # type: ignore[assignment]
    questions_to_me: int = Field(default=None)  # type: ignore[assignment]


class BranchStatusOut(_Strict):
    phase_id: uuid.UUID
    discipline_id: uuid.UUID
    status: BranchStatusValue
    changed_by: UserRef | None
    changed_at: str
    open_questions: int
    has_expert: bool


class HoursTotals(_Strict):
    e: str
    sigma: str = Field(default=None)  # type: ignore[assignment]
    p80: str
    p90: str


class TreeTotals(_Strict):
    works: HoursTotals
    pm: HoursTotals
    total: HoursTotals
    unaccounted_leaves: int
    nodes_count: int
    nodes_limit: Literal[5000]


class Tree(_Strict):
    project_version: int
    nodes: list[NodeOut] = Field(max_length=6000)
    branch_statuses: list[BranchStatusOut]
    totals: TreeTotals


# --- состояние вида ----------------------------------------------------------------------------


class ViewState(_Strict):
    state: dict[str, Any]


# --- календарь --------------------------------------------------------------------------------


class CalendarDay(_Strict):
    date: dt.date
    is_working: bool


class CalendarYear(_Strict):
    year: int = Field(ge=2000, le=2100)
    days: list[CalendarDay]


class CalendarList(_Strict):
    items: list[CalendarYear]


class CalendarMonth(_Strict):
    month: int = Field(ge=1, le=12)
    working_days: int
    non_working: list[dt.date]
    working_weekends: list[dt.date]


class CalendarPreview(_Strict):
    year: int
    months: list[CalendarMonth]
    saved: bool


# --- уведомления ------------------------------------------------------------------------------


class NotificationOut(_Strict):
    id: uuid.UUID
    kind: str
    project_id: uuid.UUID | None
    node_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: str
    read_at: str | None


class NotificationList(_Strict):
    items: list[NotificationOut]
    unread: int
    next_cursor: str | None


class NotificationsRead(_Strict):
    ids: list[uuid.UUID] = Field(default=None)  # type: ignore[assignment]
    all: bool = False


# --- статус проекта ---------------------------------------------------------------------------


class StatusChange(_Strict):
    to: ProjectStatus
    reason: str = Field(default=None, min_length=10, max_length=500)  # type: ignore[assignment]


class StatusWarning(_Strict):
    code: Literal[
        "branches_not_done", "open_customer_questions", "no_snapshot", "disciplines_without_expert"
    ]
    count: int


class StatusChangeResult(_Strict):
    status: ProjectStatus
    project_version: int
    warnings: list[StatusWarning]


# --- команда ----------------------------------------------------------------------------------


class MemberIn(_Strict):
    user_id: uuid.UUID
    role: ProjectRole
    discipline_id: uuid.UUID | None = None
    is_reviewer: bool = False


class MembersPut(_Strict):
    members: list[MemberIn]


class MemberOut(_Strict):
    user: UserRef
    role: ProjectRole
    discipline_id: uuid.UUID | None
    is_reviewer: bool
    status: Literal["active", "blocked", "pending_password"]
    added_by_admin_self: bool


class MemberList(_Strict):
    items: list[MemberOut]


class MemberReplace(_Strict):
    replacement_user_id: uuid.UUID


# --- дисциплины проекта -----------------------------------------------------------------------


class DisciplineAdd(_Strict):
    discipline_id: uuid.UUID


class DisciplineProfilePatch(_Strict):
    profile_id: uuid.UUID


class BranchStatusChange(_Strict):
    phase_id: uuid.UUID
    discipline_id: uuid.UUID
    status: BranchStatusValue
    was: BranchStatusValue


class NodesMutation(_Strict):
    nodes: list[NodeOut]
    deleted_ids: list[uuid.UUID] = Field(default=None)  # type: ignore[assignment]
    project_version: int
    totals: HoursTotals
    branch_statuses: list[BranchStatusChange]
    batch_id: uuid.UUID | None = None


class MemberCandidate(_Strict):
    user: UserRef
    system_roles: list[SystemRole]


class MemberCandidates(_Strict):
    items: list[MemberCandidate]


# --- типы узлов проекта (CORE-020, CR-006) ----------------------------------------------------


class Norm(_Strict):
    label: str = Field(min_length=1, max_length=50)
    o: DecimalString
    r: DecimalString
    p: DecimalString


class NodeType(_Strict):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=50)
    icon: str = Field(max_length=64)
    norms: list[Norm] = Field(max_length=20)
    is_system: bool
    is_active: bool
    project_id: uuid.UUID | None


class NodeTypeList(_Strict):
    items: list[NodeType]


class LocalNodeType(_Strict):
    name: str = Field(min_length=1, max_length=50)
    icon: NodeTypeIcon


# --- узлы: создание и правка (CORE-015) -------------------------------------------------------

#: ``HoursInput``: O/R/P на вход строкой, ``null`` — очистить (BR-CALC-03)
HoursInput = str | None
_HOURS_PATTERN = r"^\d+([.,]\d+)?$"


class NodeCreate(_Strict):
    parent_id: uuid.UUID
    after_id: uuid.UUID | None = None
    type_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    o: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    r: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    p: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    multiplier: int = Field(default=None, ge=1, le=10000)  # type: ignore[assignment]


class NodeChanges(_Strict):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"minProperties": 1})

    title: str = Field(default=None, min_length=1, max_length=200)  # type: ignore[assignment]
    type_id: uuid.UUID | None = None
    o: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    r: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    p: HoursInput = Field(default=None, pattern=_HOURS_PATTERN, max_length=12)
    multiplier: int = Field(default=None, ge=1, le=10000)  # type: ignore[assignment]
    comment_lines: list[CommentLine] | None = Field(default=None, max_length=10)


class NodePatch(_Strict):
    base_version: int = Field(ge=1)
    changes: NodeChanges


class AncestorTotals(_Strict):
    id: uuid.UUID
    e: str
    sigma: str


class NodeMutation(_Strict):
    node: NodeOut
    project_version: int
    ancestors: list[AncestorTotals]
    totals: HoursTotals
    branch_status: BranchStatusChange | None
    rounded: list[str] = Field(default=None)  # type: ignore[assignment]
