"""Схемы статистики (CORE-050…053; contracts/openapi.yaml ``Stats``, ``RemindResult``)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.v1.snapshot_schemas import HoursTotals
from estimator.db.enums import BranchStatusValue, QuoteFigure


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Flag = Literal["large", "wide_fork", "open_question", "no_expert", "overdue"]


class ReadinessCell(_Strict):
    phase_id: uuid.UUID
    discipline_id: uuid.UUID
    e: str
    status: BranchStatusValue
    last_change_at: dt.datetime | None
    flags: list[Flag]
    overdue_working_days: int | None


class PhaseTotal(_Strict):
    phase_id: uuid.UUID
    hours: HoursTotals
    share_pct: str | None


class DisciplineTotal(_Strict):
    discipline_id: uuid.UUID
    hours: HoursTotals
    share_pct: str | None


class StatsTotals(_Strict):
    by_phase: list[PhaseTotal]
    by_discipline: list[DisciplineTotal]
    works: HoursTotals
    pm: HoursTotals
    total: HoursTotals
    quote_figure: QuoteFigure
    duration_weeks: int | None


class RatioOut(_Strict):
    ratio_id: uuid.UUID
    pct: str | None
    min_pct: str
    max_pct: str
    verdict: Literal["ok", "below", "above"] | None


class VolumeOut(_Strict):
    type_id: uuid.UUID
    name: str
    count: int


class LargeCandidate(_Strict):
    node_id: uuid.UUID
    e_unit: str
    e: str
    repeating: bool


class WideFork(_Strict):
    node_id: uuid.UUID
    ratio_pct: str


class Candidates(_Strict):
    large: list[LargeCandidate]
    wide_fork: list[WideFork]


class TagItem(_Strict):
    node_id: uuid.UUID
    tag_id: uuid.UUID
    text: str
    path: list[str]


class TagList(_Strict):
    category: Literal["assumption", "constraint", "risk", "tech"]
    items: list[TagItem]


class Reviewed(_Strict):
    discipline_id: uuid.UUID
    reviewed_pct: str | None
    self_review_pct: str | None


class DynamicsPoint(_Strict):
    date: dt.date
    e: str | None
    p80: str | None


class MoneyRow(_Strict):
    discipline_id: uuid.UUID | None
    amount: str


class MoneyFigure(_Strict):
    k: str | None
    rows_rub: list[MoneyRow]
    total_rub: str | None
    vat_rub: str | None
    total_with_vat_rub: str | None
    rows_cur: list[MoneyRow]
    total_cur: str | None
    vat_cur: str | None
    total_with_vat_cur: str | None


class Figures(_Strict):
    e: MoneyFigure = Field(default=None)  # type: ignore[assignment]
    p80: MoneyFigure = Field(default=None)  # type: ignore[assignment]
    p90: MoneyFigure = Field(default=None)  # type: ignore[assignment]


class CostByDiscipline(_Strict):
    discipline_id: uuid.UUID | None
    cost_rub: str | None


class CostByPhase(_Strict):
    phase_id: uuid.UUID
    cost_rub: str | None


class MoneyDynamics(_Strict):
    date: dt.date
    quote_cur: str | None


class SnapshotQuote(_Strict):
    snapshot_id: uuid.UUID
    quote_cur: str | None


class StatsMoney(_Strict):
    cost_by_discipline: list[CostByDiscipline] = Field(default=None)  # type: ignore[assignment]
    cost_by_phase: list[CostByPhase] = Field(default=None)  # type: ignore[assignment]
    figures: Figures = Field(default=None)  # type: ignore[assignment]
    dynamics: list[MoneyDynamics] = Field(default=None)  # type: ignore[assignment]
    snapshots: list[SnapshotQuote] = Field(default=None)  # type: ignore[assignment]


class Stats(_Strict):
    project_version: int
    readiness: list[ReadinessCell]
    totals: StatsTotals
    ratios: list[RatioOut]
    volumes: list[VolumeOut]
    candidates: Candidates
    tag_lists: list[TagList]
    reviewed: list[Reviewed]
    dynamics: list[DynamicsPoint]
    money: StatsMoney = Field(default=None)  # type: ignore[assignment]


class RemindResult(_Strict):
    sent_to: int
