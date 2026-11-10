"""CORE-030 · деньги проекта: чтение и правка (SPEC BR-MONEY-01…05, FR-PRJ-01, 6.4, 11.6 №7–9,
№13–14, SEC-AUTHZ-04, SEC-AUD-01; 15.2 ``GET/PUT /projects/{id}/money``).

* Право и TOTP проверяет gate (``money.read`` / ``money.write`` с ``totp_gate``); сюда приходят
  только те, кому деньги можно показать.
* Валюта — из справочника (активная); для RUB курс всегда 1. Курс > 0, до 4 знаков. НДС — ставка
  справочника, в проект копируется её процент (C-31). Ставки — целые ₽/ч 0–1 000 000 по
  дисциплинам проекта и УП (``discipline_id = null``); ``rate_rub = null`` убирает ставку.
* Итоги «Деньги» считает :mod:`estimator.domain.calc.money` (CORE-005) по дереву проекта.
* Аудит ``project.money.changed`` — только факт и названия полей (SEC-AUD-01), значения «было →
  стало» — в журнал проекта с признаком ``is_money`` (история для модераторов, CORE-032).
* Событие ``money.updated`` уходит в канал ``project:{id}:money`` (без новой версии проекта:
  дерево не меняется), кэш итогов пересчитывается (CORE-026).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.models.dictionaries import Currency, VatRate
from estimator.db.models.money import ProjectMoney, ProjectRate
from estimator.db.models.projects import Project, ProjectDiscipline
from estimator.db.uuid7 import uuid7
from estimator.domain import calc
from estimator.domain.calc.model import PM_ROW
from estimator.realtime.bus import publish
from estimator.security import audit
from estimator.services.projects import journal
from estimator.services.projects.totals import schedule as schedule_totals
from estimator.services.tree.load import compute

RUB = "RUB"
RATE_MAX = Decimal(1_000_000)
EXCHANGE_MAX = Decimal("99999999.9999")  # NUMERIC(12,4)


async def money_settings(db: AsyncSession, project_id: uuid.UUID) -> calc.MoneySettings | None:
    """Валюта, курс, НДС и ставки проекта — вход денежного расчёта (CORE-005)."""
    row = await db.get(ProjectMoney, project_id)
    if row is None:  # pragma: no cover — строка создаётся вместе с проектом
        return None
    rates = (
        await db.execute(
            select(ProjectRate.discipline_id, ProjectRate.rate_rub).where(
                ProjectRate.project_id == project_id
            )
        )
    ).all()
    return calc.MoneySettings(
        currency=row.currency,
        exchange_rate=row.exchange_rate,
        vat_percent=row.vat_percent,
        rates={str(d) if d else None: r for d, r in rates},
    )


def _row_id(row: str) -> str | None:
    return None if row == PM_ROW else row


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(value)


def _rows(rows: dict[str, Decimal | None]) -> list[dict[str, Any]]:
    # строка, не поместившаяся в NUMERIC(20,0), в ответ не идёт: итог уже «—» (BR-MONEY-04)
    return [
        {"discipline_id": _row_id(k), "amount": format_decimal(v)}
        for k, v in rows.items()
        if v is not None
    ]


def _figure(f: calc.FigureMoney) -> dict[str, Any]:
    return {
        "k": None if f.k is None else format_decimal(calc.round_half_up(f.k, 6)),
        "rows_rub": _rows(f.rows_rub),
        "total_rub": _money(f.total_rub),
        "vat_rub": _money(f.vat_rub),
        "total_with_vat_rub": _money(f.total_with_vat_rub),
        "rows_cur": _rows(f.rows_cur),
        "total_cur": _money(f.total_cur),
        "vat_cur": _money(f.vat_cur),
        "total_with_vat_cur": _money(f.total_with_vat_cur),
    }


@dataclass(frozen=True)
class _State:
    row: ProjectMoney
    rates: list[ProjectRate]
    result: calc.MoneyResult


async def _state(db: AsyncSession, project: Project) -> _State:
    row = await db.get(ProjectMoney, project.id, populate_existing=True)
    if row is None:  # pragma: no cover — строка создаётся вместе с проектом
        raise ApiError("NOT_FOUND")
    settings = await money_settings(db, project.id)
    if settings is None:  # pragma: no cover — строка проверена выше
        raise ApiError("NOT_FOUND")
    rates = list(
        (await db.scalars(select(ProjectRate).where(ProjectRate.project_id == project.id))).all()
    )
    tree = (await compute(db, project)).result
    return _State(row, rates, calc.calculate_money(tree, settings))


async def _disciplines(db: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.scalars(
                select(ProjectDiscipline.discipline_id).where(
                    ProjectDiscipline.project_id == project_id
                )
            )
        ).all()
    )


def _rates_out(disciplines: list[uuid.UUID], rates: list[ProjectRate]) -> list[dict[str, Any]]:
    """Ставка по каждой дисциплине проекта и УП; ``null`` — не задана."""
    by_id = {r.discipline_id: r.rate_rub for r in rates}
    keys: list[uuid.UUID | None] = [*disciplines, None]
    return [
        {
            "discipline_id": None if k is None else str(k),
            "rate_rub": _money(by_id.get(k)),
        }
        for k in keys
    ]


async def money_view(db: AsyncSession, project: Project) -> dict[str, Any]:
    """Ответ ``ProjectMoney`` (15.2 ``GET /projects/{id}/money``)."""
    return (await _view(db, project))[0]


async def _view(db: AsyncSession, project: Project) -> tuple[dict[str, Any], calc.MoneyResult]:
    st = await _state(db, project)
    by_figure = st.result.by_figure or {}
    return {
        "currency": st.row.currency,
        "exchange_rate": format_decimal(st.row.exchange_rate),
        "vat_rate_id": st.row.vat_rate_id,
        "vat_percent": _money(st.row.vat_percent),
        "rates": _rates_out(await _disciplines(db, project.id), st.rates),
        "rates_missing": list(st.result.rates_missing),
        "figures": {f.value: _figure(m) for f, m in by_figure.items()},
        "updated_at": st.row.updated_at,
        "project_version": project.version,
    }, st.result


def money_totals(result: calc.MoneyResult) -> dict[str, Any]:
    """``MoneyTotals`` события ``money.updated`` (ws-events): «в КП» и стоимость по E."""
    quote = result.quote
    by_e = None if result.by_figure is None else result.by_figure[calc.QuoteFigure.E]
    return {
        "cost_rub": _money(by_e.total_rub if by_e else None),
        "quote_rub": _money(quote.total_rub if quote else None),
        "quote_cur": _money(quote.total_cur if quote else None),
        "vat_rub": _money(quote.vat_rub if quote else None),
        "total_with_vat_rub": _money(quote.total_with_vat_rub if quote else None),
        "rates_missing": [_row_id(r) for r in result.rates_missing],
    }


@dataclass(frozen=True)
class MoneyChange:
    """Тело ``PUT /projects/{id}/money``; ``None`` — поле не передано."""

    currency: str | None = None
    exchange_rate: Decimal | None = None
    vat_rate_id: uuid.UUID | None = None
    rates: list[tuple[uuid.UUID | None, str | None]] | None = None


def _invalid(field: str, message: str, code: str = "invalid") -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": code, "message": message}],
    )


def _out_of_range(field: str, low: str, high: str, detail: str) -> ApiError:
    return ApiError("VALUE_OUT_OF_RANGE", detail=detail, field=field, min=low, max=high)


async def _check_currency(db: AsyncSession, code: str) -> None:
    active = await db.scalar(select(Currency.is_active).where(Currency.code == code))
    if not active:
        raise _invalid("currency", "Валюта не из справочника", "enum")


def _check_exchange(value: Decimal) -> Decimal:
    if value <= 0 or value > EXCHANGE_MAX:
        raise _out_of_range(
            "exchange_rate", "0.0001", format_decimal(EXCHANGE_MAX), "Курс — больше нуля"
        )
    if value != value.quantize(Decimal("0.0001")):
        raise _invalid("exchange_rate", "Курс — не больше 4 знаков после запятой", "pattern")
    return value


def _parse_rate(raw: str) -> Decimal:
    value = Decimal(raw)
    if value > RATE_MAX:
        raise _out_of_range("rates", "0", "1000000", "Ставка — от 0 до 1 000 000 ₽/ч")
    return value


async def update_money(
    db: AsyncSession, principal: Principal, project: Project, change: MoneyChange
) -> dict[str, Any]:
    """Изменить валюту, курс, НДС и ставки (``PUT /projects/{id}/money``)."""
    row = await db.get(ProjectMoney, project.id, populate_existing=True)
    if row is None:  # pragma: no cover — строка создаётся вместе с проектом
        raise ApiError("NOT_FOUND")
    journal_changes: dict[str, tuple[Any, Any]] = {}
    fields: list[str] = []
    discipline_ids: list[str] = []

    currency = change.currency if change.currency is not None else row.currency
    if change.currency is not None and change.currency != row.currency:
        await _check_currency(db, change.currency)
    rate = row.exchange_rate
    if currency == RUB:
        rate = Decimal(1)  # для RUB курс = 1, поле скрыто (BR-MONEY-03)
    elif change.exchange_rate is not None:
        rate = _check_exchange(change.exchange_rate)
    elif change.currency is not None and change.currency != row.currency:
        raise _invalid("exchange_rate", "Укажите курс новой валюты", "required")
    if currency != row.currency:
        journal_changes["currency"] = (row.currency, currency)
        fields.append("currency")
        row.currency = currency
    if rate != row.exchange_rate:
        journal_changes["exchange_rate"] = (row.exchange_rate, rate)
        fields.append("exchange_rate")
        row.exchange_rate = rate

    if change.vat_rate_id is not None and change.vat_rate_id != row.vat_rate_id:
        vat = await db.get(VatRate, change.vat_rate_id)
        if vat is None or not vat.is_active:
            raise _invalid("vat_rate_id", "Ставка НДС не из справочника", "enum")
        journal_changes["vat_percent"] = (row.vat_percent, vat.percent)
        fields.append("vat_rate")
        row.vat_rate_id, row.vat_percent = vat.id, vat.percent

    if change.rates is not None:
        allowed = set(await _disciplines(db, project.id))
        current = {
            r.discipline_id: r
            for r in (
                await db.scalars(select(ProjectRate).where(ProjectRate.project_id == project.id))
            ).all()
        }
        seen: set[uuid.UUID | None] = set()
        for discipline_id, raw in change.rates:
            if discipline_id in seen:
                raise _invalid("rates", "Ставка дисциплины указана дважды", "duplicate")
            seen.add(discipline_id)
            if discipline_id is not None and discipline_id not in allowed:
                raise _invalid("rates", "Дисциплины нет в проекте", "enum")
            value = None if raw is None else _parse_rate(raw)
            old = current.get(discipline_id)
            if (old.rate_rub if old else None) == value:
                continue
            key = "pm_rate" if discipline_id is None else "rate"
            if key not in fields:
                fields.append(key)
            if discipline_id is not None:
                discipline_ids.append(str(discipline_id))
            journal_changes[f"rate:{discipline_id or PM_ROW}"] = (
                old.rate_rub if old else None,
                value,
            )
            if value is None:
                if old is not None:
                    await db.delete(old)
            elif old is None:
                db.add(
                    ProjectRate(
                        id=uuid7(),
                        project_id=project.id,
                        discipline_id=discipline_id,
                        rate_rub=value,
                        created_by=principal.user_id,
                        updated_by=principal.user_id,
                    )
                )
            else:
                old.rate_rub = value
                old.updated_by = principal.user_id

    if fields:
        row.updated_by = principal.user_id
        await db.flush()
        journal.record(
            db,
            project.id,
            principal.user_id,
            "project.money.changed",
            journal_changes,
            is_money=True,
        )
        await audit.write(
            db,
            "project.money.changed",
            user_id=principal.user_id,
            login=principal.login,
            session_id=principal.session_id,
            object_type="project",
            object_id=project.id,
            project_id=project.id,
            details={"fields": fields, "discipline_ids": discipline_ids},
        )
        await db.refresh(row)
        view, result = await _view(db, project)
        publish(
            db,
            f"project:{project.id}:money",
            "money.updated",
            {
                "rates": view["rates"],
                "currency": view["currency"],
                "exchange_rate": view["exchange_rate"],
                "vat_percent": view["vat_percent"],
                "totals": money_totals(result),
            },
            project_version=project.version,
        )
        schedule_totals(db, project.id)
        return view
    return await money_view(db, project)


#: ``project_money.contract_amount NUMERIC(20,0)``
CONTRACT_DIGITS = 20


def parse_contract_amount(raw: str) -> Decimal:
    """Сумма договора: целое ≥ 0 (``MoneyString``), не больше 20 цифр (BR-PRJ-05, CR-002)."""
    digits = raw.lstrip("0") or "0"
    if len(digits) > CONTRACT_DIGITS:
        raise _out_of_range(
            "contract_amount",
            "0",
            "9" * CONTRACT_DIGITS,
            "Сумма договора не помещается в хранилище",
        )
    return Decimal(digits)


async def contract_amount(db: AsyncSession, project_id: uuid.UUID) -> Decimal | None:
    row = await db.get(ProjectMoney, project_id)
    return None if row is None else row.contract_amount


async def set_contract_amount(
    db: AsyncSession, principal: Principal, project: Project, value: Decimal | None
) -> bool:
    """Записать сумму договора (CORE-029) через сервис денег: журнал с ``is_money``, аудит
    ``project.money.changed`` без суммы, ``money.updated`` в ``:money``, пересчёт кэша итогов
    (сводка по портфелю берёт сумму оттуда). ``False`` — значение не изменилось."""
    row = await db.get(ProjectMoney, project.id, populate_existing=True)
    if row is None:  # pragma: no cover — строка создаётся вместе с проектом
        raise ApiError("NOT_FOUND")
    if row.contract_amount == value:
        return False
    old = row.contract_amount
    row.contract_amount = value
    row.updated_by = principal.user_id
    await db.flush()
    journal.record(
        db,
        project.id,
        principal.user_id,
        "project.money.changed",
        {"contract_amount": (old, value)},
        is_money=True,
    )
    await audit.write(
        db,
        "project.money.changed",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project",
        object_id=project.id,
        project_id=project.id,
        details={"fields": ["contract_amount"], "discipline_ids": []},
    )
    _view_body, result = await _view(db, project)
    publish(
        db,
        f"project:{project.id}:money",
        "money.updated",
        {"contract_amount": _money(value), "totals": money_totals(result)},
        project_version=project.version,
    )
    schedule_totals(db, project.id)
    return True
