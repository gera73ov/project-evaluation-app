"""Производственный календарь (ADM-008; contracts/openapi.yaml «Администратор»,
``GET/POST /admin/calendar``, ``PUT/DELETE /admin/calendar/{year}``).

CSV data.gov.ru ≤ 256 КБ (SEC-WEB-08): ``dry_run=true`` (по умолчанию) — только предпросмотр по
месяцам, ``false`` — сохранение года. Права ``dict.read`` и ``dict.write`` (администратор).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import File, Form, Path, Query, Response, UploadFile

from estimator.admin import calendar
from estimator.admin.calendar import csvfile
from estimator.api.common.errors import ApiError
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.session import DbSession

router = ApiRouter(tags=["Администратор"])
Year = Annotated[int, Path(ge=csvfile.YEAR_MIN, le=csvfile.YEAR_MAX)]


def _flag(raw: str | None, *, default: bool) -> bool:
    """Флажок формы. FastAPI считает отсутствующее булево поле формы ``false`` (как HTML-флажок),
    а по контракту ``dry_run`` по умолчанию ``true`` — поэтому поле читается строкой."""
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in ("true", "1", "on", "yes"):
        return True
    if value in ("false", "0", "off", "no"):
        return False
    raise ApiError(
        "VALIDATION_FAILED",
        detail="dry_run — true или false",
        errors=[{"field": "/dry_run", "code": "type", "message": "Ожидается true или false"}],
    )


@router.get("/admin/calendar", permission="dict.read", response_model=s.CalendarList)
async def list_calendar(
    db: DbSession, year: Annotated[int | None, Query()] = None
) -> dict[str, Any]:
    return {"items": await calendar.list_years(db, year)}


@router.post("/admin/calendar", permission="dict.write", response_model=s.CalendarPreview)
async def upload_calendar(
    principal: ActivePrincipal,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    dry_run: Annotated[str | None, Form(max_length=5)] = None,
) -> dict[str, Any]:
    preview_only = _flag(dry_run, default=True)
    raw = await file.read(csvfile.MAX_BYTES + 1)
    if len(raw) > csvfile.MAX_BYTES:
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            detail="Файл календаря больше 256 КБ",
            limit_bytes=csvfile.MAX_BYTES,
        )
    try:
        parsed = csvfile.parse(raw)
    except csvfile.CalendarFileError as exc:
        raise ApiError(
            "VALIDATION_FAILED",
            detail=str(exc),
            errors=[{"field": exc.field, "code": "format", "message": str(exc)}],
        ) from None
    days = parsed.calendar()
    if not preview_only:
        await calendar.replace_year(db, parsed.year, days, actor=principal, op="import")
    return {
        "year": parsed.year,
        "months": calendar.month_preview(parsed.year, days),
        "saved": not preview_only,
    }


@router.put("/admin/calendar/{year}", permission="dict.write", response_model=s.CalendarYear)
async def put_calendar_year(
    year: Year, body: s.CalendarYear, principal: ActivePrincipal, db: DbSession
) -> dict[str, Any]:
    if body.year != year:
        raise ApiError(
            "VALIDATION_FAILED",
            detail="Год в теле не совпадает с годом в адресе",
            errors=[{"field": "/year", "code": "invalid", "message": "Год не совпадает"}],
        )
    days: dict[dt.date, bool] = {}
    for item in body.days:
        if item.date.year != year:
            raise ApiError(
                "VALIDATION_FAILED",
                detail=f"Дата {item.date} не из {year} года",
                errors=[{"field": "/days", "code": "invalid", "message": "Дата не из года"}],
            )
        days[item.date] = item.is_working
    return await calendar.replace_year(db, year, days, actor=principal, op="update")


@router.delete("/admin/calendar/{year}", permission="dict.write", status_code=204)
async def delete_calendar_year(year: Year, principal: ActivePrincipal, db: DbSession) -> Response:
    await calendar.delete_year(db, year, actor=principal)
    return Response(status_code=204)
