"""Запись справочников (ADM-007; SPEC 7.5, BR-ADM-01, BR-ADM-02, BR-TREE-08, C-31, Q-13).

Общее для всех справочников:

* ``POST`` создаёт запись (обязательные поля проверяются здесь: схемы записи в контракте общие для
  ``POST`` и ``PATCH``), ``PATCH`` меняет переданные поля, ``DELETE`` удаляет запись, которая
  нигде не используется; используемую — 409 ``DICTIONARY_IN_USE`` (её можно сделать неактивной).
* Каждое изменение — событие ``dict.changed`` «было → стало» (BR-ADM-01). ``op``: ``create``,
  ``update``, ``activate``/``deactivate`` (меняется только ``is_active``), ``delete``.
* Снимки хранят названия на момент снимка (BR-ADM-02) — правка справочника их не трогает.

Правила отдельных справочников:

* фазы — ровно одна сквозная: признак переносится на другую фазу, снять его с единственной
  нельзя (409); сквозную фазу не удаляют;
* дисциплины — название уникально, профиль по умолчанию — только свой;
* типы узлов — только словарь; «Работа» не удаляется и не отключается (BR-TREE-08); нормы
  «вариант — O/R/P» с O ≤ R ≤ P;
* профили — цепочка из типов словаря, название уникально в дисциплине; первый профиль дисциплины
  становится профилем по умолчанию; профиль по умолчанию не удаляется (409);
* контрольные соотношения — дисциплина A не входит в B, 0 ≤ мин ≤ макс ≤ 999,99;
* валюты — RUB не удаляется и не отключается;
* ставки НДС — «Без НДС» не удаляется, не отключается и не меняет процент; ровно одна ставка по
  умолчанию (C-31): признак переносится, снять с единственной нельзя, отключить её нельзя.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import any_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.dictionaries import read
from estimator.api.common.decimal import format_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import CommentTagCategory
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
from estimator.security import audit
from estimator.services.tree.local_types import type_out

RUB = "RUB"
PCT_MAX = Decimal("999.99")

Data = dict[str, Any]
Hook = Callable[[AsyncSession, Any, Data, bool], Awaitable[None]]
DeleteHook = Callable[[AsyncSession, Any], Awaitable[None]]


def invalid(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


def in_use(message: str) -> ApiError:
    return ApiError("DICTIONARY_IN_USE", detail=message)


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _diff(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> dict[str, list[Any]]:
    keys = [k for k in (after or before or {}) if k != "id"]
    old, new = before or {}, after or {}
    return {
        k: [_plain(old.get(k)), _plain(new.get(k))]
        for k in keys
        if _plain(old.get(k)) != _plain(new.get(k))
    }


@dataclass(frozen=True)
class Dictionary:
    name: str  # ``details.dictionary`` события dict.changed
    model: type[Any]
    out: Callable[[Any], dict[str, Any]]
    required: tuple[str, ...]
    validate: Hook
    before_delete: DeleteHook
    defaults: Callable[[AsyncSession], Awaitable[Data]] | None = None
    key: str = "id"


async def _audit(
    db: AsyncSession,
    actor: Principal,
    spec: Dictionary,
    op: str,
    object_id: Any,
    changes: dict[str, list[Any]],
) -> None:
    await audit.write(
        db, "dict.changed", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="dictionary_item",
        object_id=f"{spec.name}:{object_id}",
        details={"dictionary": spec.name, "op": op, "changes": changes},
    )  # fmt: skip


async def _get(db: AsyncSession, spec: Dictionary, key: Any) -> Any:
    row = await db.get(spec.model, key, with_for_update=True)
    if row is None or (spec.model is NodeType and row.project_id is not None):
        raise ApiError("NOT_FOUND")
    return row


def _apply(row: Any, data: Data) -> None:
    for field, value in data.items():
        setattr(row, field, value)


async def create(
    db: AsyncSession, actor: Principal, spec: Dictionary, data: Data
) -> dict[str, Any]:
    missing = [f for f in spec.required if data.get(f) is None]
    if missing:
        raise invalid(missing[0], "Обязательное поле")
    values = {**(await spec.defaults(db) if spec.defaults else {}), **data}
    row = spec.model()
    await spec.validate(db, row, values, True)
    _apply(row, values)
    row.created_by = actor.user_id
    row.updated_by = actor.user_id
    db.add(row)
    await db.flush()
    await db.refresh(row)
    after = spec.out(row)
    await _audit(db, actor, spec, "create", after[spec.key], _diff(None, after))
    return after


async def change(
    db: AsyncSession, actor: Principal, spec: Dictionary, key: Any, data: Data
) -> dict[str, Any]:
    row = await _get(db, spec, key)
    before = spec.out(row)
    await spec.validate(db, row, data, False)
    _apply(row, data)
    row.updated_by = actor.user_id
    await db.flush()
    await db.refresh(row)
    after = spec.out(row)
    changes = _diff(before, after)
    if changes:
        op = "update"
        if set(changes) == {"is_active"}:
            op = "activate" if after["is_active"] else "deactivate"
        await _audit(db, actor, spec, op, after[spec.key], changes)
    return after


async def remove(db: AsyncSession, actor: Principal, spec: Dictionary, key: Any) -> None:
    row = await _get(db, spec, key)
    before = spec.out(row)
    await spec.before_delete(db, row)
    try:
        async with db.begin_nested():
            await db.delete(row)
            await db.flush()
    except IntegrityError as exc:  # ссылка из проектов, дерева или других справочников
        raise in_use("Запись используется: её можно только сделать неактивной") from exc
    await _audit(db, actor, spec, "delete", before[spec.key], _diff(before, None))


# --- проверки, общие для нескольких справочников ----------------------------------------------


def _text(data: Data, field: str) -> None:
    if field in data and data[field] is not None:
        data[field] = str(data[field]).strip()
        if not data[field]:
            raise invalid(field, "Поле не может быть пустым")


async def _unique_name(
    db: AsyncSession, column: Any, row: Any, data: Data, *extra: Any, field: str = "name"
) -> None:
    if field not in data:
        return
    stmt = select(column).where(func.lower(column) == str(data[field]).lower(), *extra)
    if getattr(row, "id", None) is not None:
        stmt = stmt.where(column.table.c.id != row.id)
    if await db.scalar(stmt.limit(1)) is not None:
        raise ApiError("ALREADY_EXISTS", field=field)


def _no_null(data: Data, *fields: str) -> None:
    for field in fields:
        if field in data and data[field] is None:
            raise invalid(field, "Поле не может быть пустым")


async def _nothing(db: AsyncSession, row: Any) -> None:
    del db, row


# --- фазы ---------------------------------------------------------------------------------------


async def _phase_defaults(db: AsyncSession) -> Data:
    last = await db.scalar(select(func.max(Phase.sort_order)))
    return {"sort_order": (last or 0) + 10, "is_cross_cutting": False, "is_active": True}


async def _phase_validate(db: AsyncSession, row: Phase, data: Data, creating: bool) -> None:
    _no_null(data, "name", "sort_order", "is_cross_cutting", "is_active")
    _text(data, "name")
    wanted = data.get("is_cross_cutting")
    if wanted is True and not row.is_cross_cutting:
        # ровно одна сквозная фаза: признак переносится (уникальный индекс phases_one_cross_cutting)
        await db.execute(update(Phase).where(Phase.is_cross_cutting).values(is_cross_cutting=False))
        await db.flush()
    elif wanted is False and row.is_cross_cutting and not creating:
        raise in_use("Сквозная фаза — ровно одна: отметьте сквозной другую фазу")


async def _phase_delete(db: AsyncSession, row: Phase) -> None:
    del db
    if row.is_cross_cutting:
        raise in_use("Сквозную фазу нельзя удалить")


PHASES = Dictionary(
    "phases", Phase, read.phase_out, ("name",), _phase_validate, _phase_delete, _phase_defaults
)


# --- дисциплины ---------------------------------------------------------------------------------


async def _discipline_validate(
    db: AsyncSession, row: Discipline, data: Data, creating: bool
) -> None:
    _no_null(data, "name", "short_name", "color", "is_active")
    for field in ("name", "short_name"):
        _text(data, field)
    await _unique_name(db, Discipline.name, row, data)
    profile_id = data.get("default_profile_id")
    if profile_id is not None:
        owner = await db.scalar(
            select(DisciplineProfile.discipline_id).where(DisciplineProfile.id == profile_id)
        )
        if creating or owner != row.id:
            raise invalid("default_profile_id", "Профиль по умолчанию — из профилей дисциплины")
    elif "default_profile_id" in data and not creating and row.default_profile_id is not None:
        raise in_use("У дисциплины есть профили: выберите профиль по умолчанию")


async def _discipline_delete(db: AsyncSession, row: Discipline) -> None:
    used = await db.scalar(
        select(ControlRatio.id).where(row.id == any_(ControlRatio.disciplines_b)).limit(1)
    )
    profiles = await db.scalar(
        select(DisciplineProfile.id).where(DisciplineProfile.discipline_id == row.id).limit(1)
    )
    if used is not None or profiles is not None:
        raise in_use("Дисциплина используется в профилях или контрольных соотношениях")


async def _discipline_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True}


DISCIPLINES = Dictionary(
    "disciplines",
    Discipline,
    read.discipline_out,
    ("name", "short_name", "color"),
    _discipline_validate,
    _discipline_delete,
    _discipline_defaults,
)


# --- типы узлов ---------------------------------------------------------------------------------


def _norms(raw: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for i, norm in enumerate(raw):
        o, r, p = (Decimal(str(norm[k])) for k in ("o", "r", "p"))
        if not Decimal(0) <= o <= r <= p:
            raise invalid(f"norms/{i}", "Нормы: 0 ≤ O ≤ R ≤ P")
        out.append({"label": str(norm["label"]).strip(), "o": format_decimal(o),
                    "r": format_decimal(r), "p": format_decimal(p)})  # fmt: skip
    return out


async def _type_validate(db: AsyncSession, row: NodeType, data: Data, creating: bool) -> None:
    data.pop("is_system", None)  # readOnly: «Работа» — системный тип миграции DB-010
    _no_null(data, "name", "icon", "norms", "is_active")
    _text(data, "name")
    await _unique_name(db, NodeType.name, row, data, NodeType.project_id.is_(None))
    if "norms" in data:
        data["norms"] = _norms(data["norms"])
    if row.is_system and data.get("is_active") is False:
        raise in_use("Тип «Работа» нельзя отключить: это тип по умолчанию")
    if creating:
        data.setdefault("norms", [])


async def _type_delete(db: AsyncSession, row: NodeType) -> None:
    if row.is_system:
        raise in_use("Тип «Работа» нельзя удалить: это тип по умолчанию")
    chain = await db.scalar(
        select(DisciplineProfile.id).where(row.id == any_(DisciplineProfile.type_chain)).limit(1)
    )
    if chain is not None:
        raise in_use("Тип входит в цепочку профиля дисциплины")


async def _type_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True}


NODE_TYPES = Dictionary(
    "node_types", NodeType, type_out, ("name", "icon"), _type_validate, _type_delete, _type_defaults
)


# --- профили дисциплин --------------------------------------------------------------------------


async def _profile_validate(
    db: AsyncSession, row: DisciplineProfile, data: Data, creating: bool
) -> None:
    if data.pop("is_active", True) is False:
        raise invalid("is_active", "Профиль не отключается: его можно удалить")
    _no_null(data, "discipline_id", "name", "type_chain")
    _text(data, "name")
    discipline_id = data.get("discipline_id", row.discipline_id)
    if "discipline_id" in data:
        if await db.get(Discipline, data["discipline_id"]) is None:
            raise invalid("discipline_id", "Дисциплина не найдена")
        if not creating and data["discipline_id"] != row.discipline_id:
            is_default = await db.scalar(
                select(Discipline.id).where(Discipline.default_profile_id == row.id)
            )
            if is_default is not None:
                raise in_use("Профиль по умолчанию нельзя перенести в другую дисциплину")
    if "name" in data:
        await _unique_name(
            db, DisciplineProfile.name, row, data, DisciplineProfile.discipline_id == discipline_id
        )
    if "type_chain" in data:
        chain = list(data["type_chain"])
        known = set(
            await db.scalars(
                select(NodeType.id).where(NodeType.id.in_(chain), NodeType.project_id.is_(None))
            )
        )
        if set(chain) - known:
            raise invalid("type_chain", "Цепочка — из типов узлов словаря")
        data["type_chain"] = chain


async def _profile_delete(db: AsyncSession, row: DisciplineProfile) -> None:
    is_default = await db.scalar(
        select(Discipline.id).where(Discipline.default_profile_id == row.id)
    )
    if is_default is not None:
        raise in_use("Профиль по умолчанию нельзя удалить: сначала выберите другой")


async def create_profile(db: AsyncSession, actor: Principal, data: Data) -> dict[str, Any]:
    """Профиль; первый профиль дисциплины становится профилем по умолчанию."""
    out = await create(db, actor, PROFILES, data)
    discipline = await db.get(Discipline, out["discipline_id"], with_for_update=True)
    if discipline is not None and discipline.default_profile_id is None:
        await change(db, actor, DISCIPLINES, discipline.id, {"default_profile_id": out["id"]})
    return out


PROFILES = Dictionary(
    "profiles",
    DisciplineProfile,
    read.profile_out,
    ("discipline_id", "name", "type_chain"),
    _profile_validate,
    _profile_delete,
)


# --- контрольные соотношения --------------------------------------------------------------------


async def _ratio_validate(db: AsyncSession, row: ControlRatio, data: Data, creating: bool) -> None:
    del creating
    _no_null(data, "discipline_a_id", "disciplines_b", "min_pct", "max_pct", "is_active")
    a = data.get("discipline_a_id", row.discipline_a_id)
    b = list(dict.fromkeys(data.get("disciplines_b", row.disciplines_b or [])))
    if "disciplines_b" in data:
        data["disciplines_b"] = b
    ids = {a, *b}
    found = set(await db.scalars(select(Discipline.id).where(Discipline.id.in_(ids))))
    if ids - found:
        raise invalid("disciplines_b", "Дисциплина не найдена")
    if a in b:
        raise invalid("disciplines_b", "Дисциплина A не входит в набор B")
    low = Decimal(str(data.get("min_pct", row.min_pct)))
    high = Decimal(str(data.get("max_pct", row.max_pct)))
    for field, value in (("min_pct", low), ("max_pct", high)):
        if value != value.quantize(Decimal("0.01")):
            raise invalid(field, "Не больше двух знаков после запятой")
    if not Decimal(0) <= low <= high <= PCT_MAX:
        raise invalid("max_pct", "0 ≤ мин ≤ макс ≤ 999,99")


async def _ratio_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True}


RATIOS = Dictionary(
    "ratios",
    ControlRatio,
    read.ratio_out,
    ("discipline_a_id", "disciplines_b", "min_pct", "max_pct"),
    _ratio_validate,
    _nothing,
    _ratio_defaults,
)


# --- метки комментариев -------------------------------------------------------------------------


async def _tag_validate(db: AsyncSession, row: CommentTag, data: Data, creating: bool) -> None:
    del db, row, creating
    _no_null(data, "name", "short_name", "color", "category", "is_active")
    for field in ("name", "short_name"):
        _text(data, field)
    if "category" in data:
        data["category"] = CommentTagCategory(data["category"])


_TAG_USED = text(
    "SELECT 1 FROM nodes WHERE comment_lines @> jsonb_build_array(jsonb_build_object("
    "'tag_id', CAST(:id AS text))) LIMIT 1"
)


async def _tag_delete(db: AsyncSession, row: CommentTag) -> None:
    if (await db.execute(_TAG_USED, {"id": str(row.id)})).first() is not None:
        raise in_use("Метка есть в комментариях: её можно только сделать неактивной")


async def _tag_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True}


TAGS = Dictionary(
    "tags",
    CommentTag,
    read.tag_out,
    ("name", "short_name", "color", "category"),
    _tag_validate,
    _tag_delete,
    _tag_defaults,
)


# --- валюты -------------------------------------------------------------------------------------


async def _currency_validate(db: AsyncSession, row: Currency, data: Data, creating: bool) -> None:
    _no_null(data, "code", "symbol", "is_active")
    if creating:
        if await db.get(Currency, data["code"]) is not None:
            raise ApiError("ALREADY_EXISTS", field="code")
    elif "code" in data and data.pop("code") != row.code:
        raise invalid("code", "Код валюты не меняется")
    if row.code == RUB and data.get("is_active") is False:
        raise in_use("RUB нельзя отключить")


async def _currency_delete(db: AsyncSession, row: Currency) -> None:
    del db
    if row.code == RUB:
        raise in_use("RUB нельзя удалить")


async def _currency_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True}


CURRENCIES = Dictionary(
    "currencies",
    Currency,
    read.currency_out,
    ("code", "symbol"),
    _currency_validate,
    _currency_delete,
    _currency_defaults,
    key="code",
)


# --- ставки НДС ---------------------------------------------------------------------------------


async def _vat_validate(db: AsyncSession, row: VatRate, data: Data, creating: bool) -> None:
    _no_null(data, "name", "is_default", "is_active")
    _text(data, "name")
    no_vat = not creating and row.percent is None
    if "percent" in data:
        value = data["percent"]
        if no_vat and value is not None:
            raise in_use("Процент ставки «Без НДС» не меняется")
        if value is not None:
            value = Decimal(str(value))
            if not Decimal(0) <= value <= 100 or value != value.quantize(Decimal("0.01")):
                raise invalid("percent", "Процент — от 0 до 100, не больше двух знаков")
            data["percent"] = value
        elif not no_vat:
            raise invalid("percent", "Ставка «Без НДС» уже есть")
    elif creating:
        raise invalid("percent", "Обязательное поле")
    active = data.get("is_active", True if creating else row.is_active)
    if no_vat and active is False:
        raise in_use("Ставку «Без НДС» нельзя отключить")
    default = data.get("is_default")
    current_default = not creating and row.is_default
    if default is True and not current_default:
        if active is False:
            raise invalid("is_default", "Ставка по умолчанию должна быть активной")
        await db.execute(update(VatRate).where(VatRate.is_default).values(is_default=False))
        await db.flush()
    elif current_default and (default is False or active is False):
        raise in_use("Ставка по умолчанию — ровно одна: отметьте по умолчанию другую ставку")


async def _vat_delete(db: AsyncSession, row: VatRate) -> None:
    del db
    if row.percent is None:
        raise in_use("Ставку «Без НДС» нельзя удалить")
    if row.is_default:
        raise in_use("Ставку по умолчанию нельзя удалить: сначала выберите другую")


async def _vat_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True, "is_default": False}


VAT_RATES = Dictionary(
    "vat_rates",
    VatRate,
    read.vat_out,
    ("name",),
    _vat_validate,
    _vat_delete,
    _vat_defaults,
)


# --- причины проигрыша --------------------------------------------------------------------------


async def _loss_validate(db: AsyncSession, row: LossReason, data: Data, creating: bool) -> None:
    del db, row, creating
    _no_null(data, "name", "is_other", "is_active")
    _text(data, "name")


async def _loss_defaults(db: AsyncSession) -> Data:
    del db
    return {"is_active": True, "is_other": False}


LOSS_REASONS = Dictionary(
    "loss_reasons",
    LossReason,
    read.loss_reason_out,
    ("name",),
    _loss_validate,
    _nothing,
    _loss_defaults,
)
