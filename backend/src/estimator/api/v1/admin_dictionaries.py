"""Справочники: чтение (ADM-007; SPEC 7.5, 3.3, GAP-13; contracts/openapi.yaml «Администратор»).

``GET /admin/<справочник>`` и ``GET /admin/method-settings`` — право ``dict.read``: администратор
и все роли, которым матрица 3.3 показывает справочники (модератор, эксперт, ревьюер, пресейл,
руководитель пресейла); суперадминистратор и аудитор ИБ — 403.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query

from estimator.admin.dictionaries import method, read
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
IncludeInactive = Annotated[bool, Query()]


@router.get("/admin/phases", permission="dict.read", response_model=s.PhaseList)
async def list_phases(db: DbSession, include_inactive: IncludeInactive = False) -> dict[str, Any]:
    return {"items": await read.phases(db, include_inactive=include_inactive)}


@router.get("/admin/disciplines", permission="dict.read", response_model=s.DisciplineList)
async def list_disciplines(
    db: DbSession, include_inactive: IncludeInactive = False
) -> dict[str, Any]:
    return {"items": await read.disciplines(db, include_inactive=include_inactive)}


@router.get("/admin/node-types", permission="dict.read", response_model=s.NodeTypeList)
async def list_node_types(
    db: DbSession, include_inactive: IncludeInactive = False
) -> dict[str, Any]:
    return {"items": await read.node_types(db, include_inactive=include_inactive)}


@router.get("/admin/profiles", permission="dict.read", response_model=s.ProfileList)
async def list_profiles(db: DbSession, include_inactive: IncludeInactive = False) -> dict[str, Any]:
    return {"items": await read.profiles(db, include_inactive=include_inactive)}


@router.get("/admin/ratios", permission="dict.read", response_model=s.RatioList)
async def list_ratios(db: DbSession, include_inactive: IncludeInactive = False) -> dict[str, Any]:
    return {"items": await read.ratios(db, include_inactive=include_inactive)}


@router.get("/admin/tags", permission="dict.read", response_model=s.TagList)
async def list_tags(db: DbSession, include_inactive: IncludeInactive = False) -> dict[str, Any]:
    return {"items": await read.tags(db, include_inactive=include_inactive)}


@router.get("/admin/currencies", permission="dict.read", response_model=s.CurrencyList)
async def list_currencies(
    db: DbSession, include_inactive: IncludeInactive = False
) -> dict[str, Any]:
    return {"items": await read.currencies(db, include_inactive=include_inactive)}


@router.get("/admin/vat-rates", permission="dict.read", response_model=s.VatRateList)
async def list_vat_rates(
    db: DbSession, include_inactive: IncludeInactive = False
) -> dict[str, Any]:
    return {"items": await read.vat_rates(db, include_inactive=include_inactive)}


@router.get("/admin/loss-reasons", permission="dict.read", response_model=s.LossReasonList)
async def list_loss_reasons(
    db: DbSession, include_inactive: IncludeInactive = False
) -> dict[str, Any]:
    return {"items": await read.loss_reasons(db, include_inactive=include_inactive)}


@router.get("/admin/method-settings", permission="dict.read", response_model=s.MethodSettings)
async def get_method_settings(db: DbSession) -> dict[str, Any]:
    return method.to_api(await method.current(db))
