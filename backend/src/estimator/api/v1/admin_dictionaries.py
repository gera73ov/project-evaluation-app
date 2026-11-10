"""Справочники (ADM-007; SPEC 7.5, 3.3, BR-ADM-01, GAP-13; contracts/openapi.yaml «Администратор»).

``GET /admin/<справочник>`` и ``GET /admin/method-settings`` — право ``dict.read``: администратор
и все роли, которым матрица 3.3 показывает справочники (модератор, эксперт, ревьюер, пресейл,
руководитель пресейла); суперадминистратор и аудитор ИБ — 403. ``POST``, ``PATCH``, ``DELETE`` и
``PUT /admin/method-settings`` — право ``dict.write`` (администратор). Правила записи —
:mod:`estimator.admin.dictionaries.write`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path, Query, Response
from pydantic import BaseModel

from estimator.admin.dictionaries import method, read, write
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import admin_schemas as s
from estimator.api.v1.core_schemas import NodeType
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
IncludeInactive = Annotated[bool, Query()]
ItemId = Annotated[uuid.UUID, Path(alias="id")]
Code = Annotated[str, Path(pattern=r"^[A-Z]{3}$")]


def _data(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


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


@router.put("/admin/method-settings", permission="dict.write", response_model=s.MethodSettings)
async def put_method_settings(
    body: s.MethodSettingsWrite, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    return await method.save(db, principal, body.model_dump())


# --- запись справочников: POST / PATCH / DELETE -----------------------------------------------


def _crud(
    path: str, spec: write.Dictionary, body_model: type[BaseModel], out_model: type[BaseModel]
) -> None:
    """Три операции справочника ``path`` с идентификатором ``{id}``."""

    async def create_item(body: Any, principal: ActivePrincipal, db: DbSession) -> Any:
        if spec is write.PROFILES:
            return await write.create_profile(db, principal, _data(body))
        return await write.create(db, principal, spec, _data(body))

    async def update_item(
        item_id: ItemId, body: Any, principal: ActivePrincipal, db: DbSession
    ) -> Any:
        return await write.change(db, principal, spec, item_id, _data(body))

    async def delete_item(item_id: ItemId, principal: ActivePrincipal, db: DbSession) -> Response:
        await write.remove(db, principal, spec, item_id)
        return Response(status_code=204)

    create_item.__annotations__["body"] = body_model
    update_item.__annotations__["body"] = body_model
    name = spec.name
    router.post(path, permission="dict.write", status_code=201, response_model=out_model,
                name=f"create_{name}")(create_item)  # fmt: skip
    router.patch(f"{path}/{{id}}", permission="dict.write", response_model=out_model,
                 name=f"update_{name}")(update_item)  # fmt: skip
    router.delete(f"{path}/{{id}}", permission="dict.write", status_code=204,
                  name=f"delete_{name}")(delete_item)  # fmt: skip


_crud("/admin/phases", write.PHASES, s.PhaseWrite, s.Phase)
_crud("/admin/disciplines", write.DISCIPLINES, s.DisciplineWrite, s.Discipline)
_crud("/admin/node-types", write.NODE_TYPES, s.NodeTypeWrite, NodeType)
_crud("/admin/profiles", write.PROFILES, s.ProfileWrite, s.Profile)
_crud("/admin/ratios", write.RATIOS, s.RatioWrite, s.Ratio)
_crud("/admin/tags", write.TAGS, s.TagWrite, s.Tag)
_crud("/admin/vat-rates", write.VAT_RATES, s.VatRateWrite, s.VatRate)
_crud("/admin/loss-reasons", write.LOSS_REASONS, s.LossReasonWrite, s.LossReason)


@router.post(
    "/admin/currencies", permission="dict.write", status_code=201, response_model=s.Currency
)
async def create_currency(
    body: s.CurrencyWrite, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    return await write.create(db, principal, write.CURRENCIES, _data(body))


@router.patch("/admin/currencies/{code}", permission="dict.write", response_model=s.Currency)
async def update_currency(
    code: Code, body: s.CurrencyWrite, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    return await write.change(db, principal, write.CURRENCIES, code, _data(body))


@router.delete("/admin/currencies/{code}", permission="dict.write", status_code=204)
async def delete_currency(code: Code, principal: ActivePrincipal, db: DbSession) -> Response:
    await write.remove(db, principal, write.CURRENCIES, code)
    return Response(status_code=204)
