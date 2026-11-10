"""CORE-029 · «Результат пресейла» (SPEC BR-PRJ-05, Q-14, 3.3, 3.4; 15.2 ``GET/PUT
/projects/{id}/outcome``).

* Результат ``unknown/won/lost/cancelled``; правят модератор, пресейл проекта и руководитель
  пресейла в любом статусе (``outcome.write``, gate).
* Причина проигрыша — из справочника; обязательна при «проигран», при «Другое» нужен текст до 500
  символов. Причина и текст хранятся только у «проигран» (CHECK ``loss_reason``): при другом
  результате они очищаются, текст без «Другое» не хранится.
* Сумма договора — в ``project_money.contract_amount`` через сервис денег; видят только роли
  с ``money.read`` (без блока ``money`` у остальных), передать её могут те, кто правит
  результат и видит деньги (``money.read`` с TOTP), в любом статусе (CR-015), и только при
  «выигран». Смена результата сумму не
  трогает: её меняет и очищает тот, у кого есть право на деньги.
* Журнал проекта — ``outcome.changed`` (без денег) и ``project.money.changed`` (``is_money``);
  событие ``project.updated`` с ``changes.outcome`` (без суммы) для всех, кто видит проект.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ProjectOutcome
from estimator.db.models.dictionaries import LossReason
from estimator.db.models.projects import Project
from estimator.realtime.bus import publish
from estimator.services.common import bump_version, log_change, user_ref
from estimator.services.money import project as money
from estimator.services.projects import journal

TEXT_MAX = 500
_UNSET: Any = object()


@dataclass(frozen=True)
class OutcomeChange:
    """Тело ``PUT``; ``contract_amount`` — :data:`_UNSET`, если поля нет в запросе."""

    outcome: ProjectOutcome
    loss_reason_id: uuid.UUID | None = None
    loss_reason_text: str | None = None
    contract_amount: Any = _UNSET

    @property
    def has_amount(self) -> bool:
        return self.contract_amount is not _UNSET


def _invalid(field: str, message: str, code: str = "invalid") -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": code, "message": message}],
    )


async def outcome_view(db: AsyncSession, project: Project, *, with_money: bool) -> dict[str, Any]:
    """Ответ ``ProjectOutcome``; блок ``money`` — только ролям с деньгами (SEC-006)."""
    body: dict[str, Any] = {
        "outcome": str(project.outcome),
        "loss_reason_id": project.loss_reason_id,
        "loss_reason_text": project.loss_reason_text,
    }
    if with_money:
        amount = await money.contract_amount(db, project.id)
        body["money"] = {"contract_amount": None if amount is None else format_decimal(amount)}
    return body


async def _reason(
    db: AsyncSession, project: Project, change: OutcomeChange
) -> tuple[uuid.UUID | None, str | None]:
    if change.outcome is not ProjectOutcome.LOST:
        return None, None
    if change.loss_reason_id is None:
        raise _invalid("loss_reason_id", "Укажите причину проигрыша", "required")
    reason = await db.get(LossReason, change.loss_reason_id)
    # выключенную причину можно оставить, если она уже стоит у проекта
    if reason is None or not (reason.is_active or reason.id == project.loss_reason_id):
        raise _invalid("loss_reason_id", "Причина не из справочника", "enum")
    if not reason.is_other:
        return reason.id, None
    text = (change.loss_reason_text or "").strip()
    if not text:
        raise _invalid("loss_reason_text", "Опишите причину проигрыша", "required")
    if len(text) > TEXT_MAX:
        raise _invalid("loss_reason_text", f"Не больше {TEXT_MAX} символов", "too_long")
    return reason.id, text


def _amount(change: OutcomeChange) -> Decimal | None:
    raw = change.contract_amount
    if raw is None:
        return None
    if change.outcome is not ProjectOutcome.WON:
        raise _invalid("contract_amount", "Сумма договора — только при «выигран»", "not_allowed")
    return money.parse_contract_amount(str(raw))


async def update_outcome(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    change: OutcomeChange,
) -> None:
    """Применить ``PUT``. Право ``money.read`` для суммы проверяет роутер до вызова (CR-015)."""
    reason_id, reason_text = await _reason(db, project, change)
    amount = _amount(change) if change.has_amount else None

    changes: dict[str, tuple[Any, Any]] = {}
    for field, new in (
        ("outcome", change.outcome),
        ("loss_reason_id", reason_id),
        ("loss_reason_text", reason_text),
    ):
        old = getattr(project, field)
        if old != new:
            changes[field] = (old, new)
            setattr(project, field, new)

    if changes:
        project.updated_by = principal.user_id
        await db.flush()
        version = await bump_version(db, project.id)
        project.version = version
        # в журнал — название причины, а не её id: справочник может измениться
        entry = {k: v for k, v in changes.items() if k != "loss_reason_id"}
        if "loss_reason_id" in changes:
            entry["loss_reason"] = await _reason_names(db, *changes["loss_reason_id"])
        journal.record(db, project.id, principal.user_id, "outcome.changed", entry)
        data = {
            "changes": journal.plain({k: new for k, (_old, new) in changes.items()}),
            "author": user_ref(principal.user_id, principal.full_name),
        }
        message = publish(
            db, f"project:{project.id}", "project.updated", data, project_version=version
        )
        log_change(db, project.id, version, message)

    if change.has_amount:
        await money.set_contract_amount(db, principal, project, amount)


async def _reason_names(
    db: AsyncSession, old: uuid.UUID | None, new: uuid.UUID | None
) -> tuple[str | None, str | None]:
    async def name(reason_id: uuid.UUID | None) -> str | None:
        if reason_id is None:
            return None
        row = await db.get(LossReason, reason_id)
        return row.name if row else None

    return await name(old), await name(new)
