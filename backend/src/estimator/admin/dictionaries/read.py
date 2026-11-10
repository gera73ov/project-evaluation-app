"""Чтение справочников (ADM-007; SPEC 7.5, 3.3; contracts/openapi.yaml ``GET /admin/<справочник>``).

Без ``include_inactive`` списки отдают только активные записи: их предлагают новые проекты и
формы. С ``include_inactive=true`` — все (админка и показ уже использованных записей).
Профили дисциплин удаляются физически (contracts/db/schema.md 2.2), поэтому всегда активны.
Типы узлов — только словарь (``project_id IS NULL``); локальные типы проектов отдаёт
``GET /projects/{id}/node-types`` (CORE-020), предложенные — ADM-009.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import (
    CommentTag,
    ControlRatio,
    Currency,
    Discipline,
    DisciplineProfile,
    LossReason,
    NodeType,
    Phase,
    VatRate,
)
from estimator.services.tree.local_types import type_out


def _active(stmt: Select[Any], column: Any, include_inactive: bool) -> Select[Any]:
    return stmt if include_inactive else stmt.where(column.is_(True))


def phase_out(row: Phase) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "sort_order": row.sort_order,
        "is_cross_cutting": row.is_cross_cutting,
        "is_active": row.is_active,
    }


def discipline_out(row: Discipline) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "short_name": row.short_name,
        "color": row.color,
        "default_profile_id": row.default_profile_id,
        "is_active": row.is_active,
    }


def profile_out(row: DisciplineProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "discipline_id": row.discipline_id,
        "name": row.name,
        "type_chain": list(row.type_chain),
        "is_active": True,
    }


def ratio_out(row: ControlRatio) -> dict[str, Any]:
    return {
        "id": row.id,
        "discipline_a_id": row.discipline_a_id,
        "disciplines_b": list(row.disciplines_b),
        "min_pct": row.min_pct,
        "max_pct": row.max_pct,
        "is_active": row.is_active,
    }


def tag_out(row: CommentTag) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "short_name": row.short_name,
        "color": row.color,
        "category": row.category.value,
        "is_active": row.is_active,
    }


def currency_out(row: Currency) -> dict[str, Any]:
    return {"code": row.code, "symbol": row.symbol, "is_active": row.is_active}


def vat_out(row: VatRate) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "percent": row.percent,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


def loss_reason_out(row: LossReason) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "is_other": row.is_other, "is_active": row.is_active}


async def phases(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(Phase), Phase.is_active, include_inactive)
    rows = await db.scalars(stmt.order_by(Phase.sort_order, Phase.name, Phase.id))
    return [phase_out(r) for r in rows]


async def disciplines(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(Discipline), Discipline.is_active, include_inactive)
    rows = await db.scalars(stmt.order_by(Discipline.name, Discipline.id))
    return [discipline_out(r) for r in rows]


async def node_types(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(NodeType), NodeType.is_active, include_inactive).where(
        NodeType.project_id.is_(None)
    )
    rows = await db.scalars(stmt.order_by(NodeType.is_system.desc(), NodeType.name, NodeType.id))
    return [type_out(r) for r in rows]


async def profiles(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    del include_inactive  # профили удаляются физически: неактивных нет
    stmt = select(DisciplineProfile).join(
        Discipline, Discipline.id == DisciplineProfile.discipline_id
    )
    rows = await db.scalars(
        stmt.order_by(Discipline.name, DisciplineProfile.name, DisciplineProfile.id)
    )
    return [profile_out(r) for r in rows]


async def ratios(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(ControlRatio), ControlRatio.is_active, include_inactive)
    stmt = stmt.join(Discipline, Discipline.id == ControlRatio.discipline_a_id)
    order = (Discipline.name, ControlRatio.created_at, ControlRatio.id)
    rows = await db.scalars(stmt.order_by(*order))
    return [ratio_out(r) for r in rows]


async def tags(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(CommentTag), CommentTag.is_active, include_inactive)
    rows = await db.scalars(stmt.order_by(CommentTag.name, CommentTag.id))
    return [tag_out(r) for r in rows]


async def currencies(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(Currency), Currency.is_active, include_inactive)
    rows = await db.scalars(stmt.order_by((Currency.code != "RUB"), Currency.code))
    return [currency_out(r) for r in rows]


async def vat_rates(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(VatRate), VatRate.is_active, include_inactive)
    rows = await db.scalars(
        stmt.order_by(VatRate.percent.asc().nulls_first(), VatRate.name, VatRate.id)
    )
    return [vat_out(r) for r in rows]


async def loss_reasons(db: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    stmt = _active(select(LossReason), LossReason.is_active, include_inactive)
    rows = await db.scalars(stmt.order_by(LossReason.is_other, LossReason.name, LossReason.id))
    return [loss_reason_out(r) for r in rows]
