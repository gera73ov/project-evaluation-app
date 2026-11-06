"""SEC-006: денег и заметок нет в ответе без права — ключа нет, а не null (SEC-AUTHZ-04)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import Field

from estimator.security.authz.engine import Access
from estimator.security.serialize import (
    MONEY_KEYS,
    PermissionAwareModel,
    for_access,
    money_field,
    notes_field,
    strip_money,
)
from tests.helpers.money_keys import assert_no_money, find_money_keys

pytestmark = [pytest.mark.spec("SEC-AUTHZ-04"), pytest.mark.spec("TC-SEC-03")]


def _access(money: bool, notes: bool = False) -> Access:
    return Access("project.read", frozenset(), "member", money=money, notes=notes)


class Discipline(PermissionAwareModel):
    name: str
    hours: Decimal
    cost: Decimal | None = money_field(default=None)


class ProjectCard(PermissionAwareModel):
    name: str
    hours: Decimal
    currency: str | None = money_field(default=None)
    contract_amount: Decimal | None = money_field(default=None)
    private_notes: str | None = notes_field(default=None)
    disciplines: list[Discipline] = Field(default_factory=list)
    lead: Discipline | None = None
    tags: list[str] = Field(default_factory=list)


CARD = ProjectCard(
    name="Портал дилеров",
    hours=Decimal("1520.5"),
    currency="RUB",
    contract_amount=None,
    private_notes="торг",
    disciplines=[Discipline(name="Бэкенд", hours=Decimal(800), cost=Decimal(2400000))],
    lead=Discipline(name="Фронтенд", hours=Decimal(10), cost=Decimal(30000)),
    tags=["CRM"],
)


def test_money_keys_absent_without_money_read() -> None:
    data = CARD.render(_access(money=False))
    assert_no_money(data)
    assert "contract_amount" not in data
    assert "private_notes" not in data
    assert data["disciplines"] == [{"name": "Бэкенд", "hours": "800"}]
    assert data["lead"] == {"name": "Фронтенд", "hours": "10"}
    assert data["tags"] == ["CRM"]


def test_money_present_with_money_read() -> None:
    data = CARD.render(_access(money=True, notes=True))
    assert data["currency"] == "RUB"
    assert data["contract_amount"] is None  # с правом null допустим
    assert data["private_notes"] == "торг"
    assert data["disciplines"][0]["cost"] == "2400000"
    assert find_money_keys(data) == ["/currency", "/contract_amount", "/disciplines/0/cost",
                                     "/lead/cost"]  # fmt: skip


def test_strip_money_recursive_and_snapshot_payload() -> None:
    event = {
        "type": "node.updated",
        "node": {"id": 1, "rate": 10, "children": [{"cost_rub": 5, "x": [{"vat": 20}]}]},
        "snapshot": {"money_payload": {"rate": 1}, "hours": 3},
        "notes": "секрет",
    }
    stripped = strip_money(event, money=False, notes=False)
    assert find_money_keys(stripped) == []
    assert stripped == {"type": "node.updated",
                        "node": {"id": 1, "children": [{"x": [{}]}]},
                        "snapshot": {"hours": 3}}  # fmt: skip
    assert strip_money(event, money=True) is event
    assert "rate" in strip_money(event, money=True, notes=False)["node"]
    assert for_access(event, _access(money=False, notes=True))["notes"] == "секрет"


def test_helper_finds_keys_at_any_depth() -> None:
    deep: object = {"currency": "USD"}
    for i in range(20):
        deep = {"level": [deep, i]} if i % 2 else {"a/b": deep}
    found = find_money_keys(deep)
    assert len(found) == 1
    assert found[0].endswith("/currency")
    assert "~1" in found[0]
    assert {"rate", "cost", "currency", "exchange_rate", "money"} <= MONEY_KEYS
    with pytest.raises(AssertionError, match="денежные ключи"):
        assert_no_money([{"exchange_rate": 92}])


STATE = {"money": False}


def _current_access() -> Access:
    return _access(money=STATE["money"])


APP = FastAPI()


@APP.get("/projects/1")
async def _card(acc: Annotated[Access, Depends(_current_access)]) -> dict[str, object]:
    return CARD.render(acc)


async def test_endpoint_without_money_read_has_no_keys() -> None:
    transport = httpx.ASGITransport(app=APP)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        STATE["money"] = False
        response = await client.get("/projects/1")
        assert response.status_code == 200
        assert_no_money(response.json())
        STATE["money"] = True
        assert find_money_keys((await client.get("/projects/1")).json())
