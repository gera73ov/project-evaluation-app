"""Схемы снимков и сравнения (CORE-060/061; contracts/openapi.yaml ``Snapshot``, ``Diff``)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from estimator.api.v1.core_schemas import UserRef


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SnapshotCreate(_Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


class HoursTotals(_Strict):
    e: str
    sigma: str = Field(default=None)  # type: ignore[assignment]
    p80: str
    p90: str


class SnapshotMoney(_Strict):
    quote_cur: str | None
    currency: str


class SnapshotOut(_Strict):
    id: uuid.UUID
    name: str
    description: str
    created_by: UserRef
    created_at: dt.datetime
    is_invalid: bool
    project_version: int
    totals: HoursTotals
    money: SnapshotMoney = Field(default=None)  # type: ignore[assignment]


class SnapshotList(_Strict):
    items: list[SnapshotOut]


class DiffSide(_Strict):
    snapshot_id: uuid.UUID | None
    label: str
    totals: HoursTotals


class DiffEstimate(_Strict):
    o: str | None
    r: str | None
    p: str | None
    multiplier: int = Field(ge=1, le=10000)
    e: str


class DiffRow(_Strict):
    node_id: uuid.UUID
    change: Literal["added", "removed", "changed", "moved"]
    title: str
    path: list[str]
    before: DiffEstimate | None
    after: DiffEstimate | None
    delta_e: str
    fields: list[str]
    last_changed_by: UserRef | None
    last_changed_at: dt.datetime | None


class DiffParam(_Strict):
    key: Literal[
        "rate", "currency", "exchange_rate", "vat", "pm_percent", "pm_base", "quote_figure",
        "phase_enabled",
    ]  # fmt: skip
    label: str
    discipline_id: uuid.UUID | None
    phase_id: uuid.UUID | None
    before: str | None
    after: str | None
    is_money: bool
    last_changed_by: UserRef | None
    last_changed_at: dt.datetime | None


class DiffPm(_Strict):
    percent_before: str
    percent_after: str
    delta_e: str


class SignedHoursTotals(_Strict):
    e: str
    sigma: str = Field(default=None)  # type: ignore[assignment]
    p80: str
    p90: str


class DiffMoneySide(_Strict):
    total_rub: str | None
    total_cur: str | None
    currency: str
    exchange_rate: str


class DiffMoneyRow(_Strict):
    node_id: uuid.UUID | None
    delta_cost_rub: str | None


class DiffMoney(_Strict):
    base: DiffMoneySide
    with_: DiffMoneySide = Field(alias="with")
    rows: list[DiffMoneyRow]
    rates_changed: bool
    rates_effect_rub: str | None
    exchange_effect_cur: str | None
    total_delta_rub: str | None
    total_delta_cur: str | None


class Diff(_Strict):
    base: DiffSide
    with_: DiffSide = Field(alias="with")
    rows: list[DiffRow]
    params: list[DiffParam]
    pm: DiffPm | None
    totals_delta: SignedHoursTotals
    money: DiffMoney = Field(default=None)  # type: ignore[assignment]
