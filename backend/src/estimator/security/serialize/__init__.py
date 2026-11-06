"""Сериализация по правам: денег и заметок нет в ответе без права (SEC-006).

SPEC SEC-AUTHZ-04, BR-MONEY-01, FR-HOME-04, FR-NOTE-01; правило R-MONEY-FIELDS в
contracts/permissions.yaml. Без действующего ``money.read`` (право выдано и TOTP пройден в
сессии) денежных ключей в ответе **нет** — не ``null`` и не пустая строка.

Два способа:

* схема ответа — подкласс :class:`PermissionAwareModel`; денежные поля объявляются через
  :func:`money_field` (заметки — :func:`notes_field`), ответ строит
  :meth:`~PermissionAwareModel.render` по решению :class:`~estimator.security.authz.engine.Access`;
* готовая структура (снимок, событие WS, выгрузка) — :func:`strip_money`, рекурсивно по ключам
  :data:`MONEY_KEYS` и ``money_payload`` снимков.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from estimator.security.authz.engine import Access

#: Денежные ключи (R-MONEY-FIELDS); на них же смотрит тестовый помощник tests/helpers/money_keys.py.
MONEY_KEYS = frozenset(
    {
        "rate",
        "rates",
        "cost",
        "currency",
        "exchange_rate",
        "money",
        "vat",
        "contract_amount",
        "quote_rub",
        "quote_cur",
        "cost_rub",
        "money_payload",
    }
)
#: Закрытые заметки (FR-NOTE-01) в общих ответах.
NOTES_KEYS = frozenset({"notes", "private_notes"})

_MONEY = "x-money"
_NOTES = "x-notes"


def money_field(**kwargs: Any) -> Any:
    """Поле, которое попадает в ответ только при ``money.read``."""
    return Field(json_schema_extra={_MONEY: True}, **kwargs)


def notes_field(**kwargs: Any) -> Any:
    """Поле с закрытыми заметками: только при ``notes.read``."""
    return Field(json_schema_extra={_NOTES: True}, **kwargs)


def _flag(info: Any, name: str) -> bool:
    extra = info.json_schema_extra
    return isinstance(extra, Mapping) and bool(extra.get(name))


class PermissionAwareModel(BaseModel):
    """Схема ответа с денежными и заметочными полями."""

    @classmethod
    def hidden_fields(cls, *, money: bool, notes: bool) -> set[str]:
        hidden: set[str] = set()
        for name, info in cls.model_fields.items():
            if (not money and _flag(info, _MONEY)) or (not notes and _flag(info, _NOTES)):
                hidden.add(name)
        return hidden

    def render(self, access: Access) -> dict[str, Any]:
        """JSON-совместимый словарь без полей, на которые нет права (вложенные модели — тоже)."""
        data = self.model_dump(
            mode="json",
            by_alias=True,
            exclude=self.hidden_fields(money=access.money, notes=access.notes),
        )
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name in data and _contains_model(value):
                data[name] = _render(value, access)
        return data


def _contains_model(value: Any) -> bool:
    if isinstance(value, PermissionAwareModel):
        return True
    return isinstance(value, list | tuple) and any(
        isinstance(v, PermissionAwareModel) for v in value
    )


def _render(value: Any, access: Access) -> Any:
    if isinstance(value, PermissionAwareModel):
        return value.render(access)
    return [_render(v, access) if isinstance(v, PermissionAwareModel) else v for v in value]


def strip_money(data: Any, *, money: bool, notes: bool = True) -> Any:
    """Копия ``data`` без денежных (и, если нужно, заметочных) ключей на любой глубине."""
    drop = (frozenset() if money else MONEY_KEYS) | (frozenset() if notes else NOTES_KEYS)
    if not drop:
        return data
    return _strip(data, drop)


def _strip(data: Any, drop: frozenset[str]) -> Any:
    if isinstance(data, Mapping):
        return {k: _strip(v, drop) for k, v in data.items() if k not in drop}
    if isinstance(data, list | tuple):
        return [_strip(v, drop) for v in data]
    return data


def for_access(data: Any, access: Access) -> Any:
    """:func:`strip_money` по решению движка прав."""
    return strip_money(data, money=access.money, notes=access.notes)
