"""CORE-001 · проверка эталонных фикстур расчёта contracts/fixtures/calc/*.json.

Тест не считает дерево (это CORE-007 и FE-002), а держит фикстуры в согласованном виде:
структура входа одинакова для всех файлов, а денежные блоки арифметически сходятся по правилам
SPEC 6.4 — итог равен сумме округлённых строк, НДС и пересчёт в валюту построчные (BR-MONEY-04).
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "calc"
PORTAL = json.loads((FIXTURES / "portal-dilerov.json").read_text(encoding="utf-8"))
EDGE = json.loads((FIXTURES / "edge-cases.json").read_text(encoding="utf-8"))

NODE_KINDS = {"phase", "discipline", "item"}
BRANCH_STATUSES = {"not_started", "draft", "done", "not_needed"}
MONEY_LIMIT = Decimal(10) ** 20  # NUMERIC(20,0)


def _round(value: Decimal, places: int = 0) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _inputs() -> list[tuple[str, dict]]:
    items = [("portal-dilerov", PORTAL["input"])]
    items += [(case["id"], case["input"]) for case in EDGE["cases"]]
    return items


@pytest.mark.parametrize(
    ("case_id", "data"), _inputs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_input_tree_is_well_formed(case_id: str, data: dict) -> None:
    phases = {p["id"]: p for p in data["phases"]}
    disciplines = {d["id"] for d in data["disciplines"]}
    nodes = {n["id"]: n for n in data["nodes"]}
    assert len(nodes) == len(data["nodes"]), f"{case_id}: повтор id узла"
    assert sum(p["is_cross_cutting"] for p in phases.values()) == 1
    for node in nodes.values():
        assert node["kind"] in NODE_KINDS
        assert node["phase_id"] in phases
        if node["kind"] == "phase":
            assert node["parent_id"] is None
            assert node["discipline_id"] is None
        else:
            assert node["parent_id"] in nodes, f"{case_id}: {node['id']} без родителя"
            assert node["discipline_id"] in disciplines
            parent = nodes[node["parent_id"]]
            assert parent["phase_id"] == node["phase_id"]
        for field in ("o", "r", "p"):
            if field in node:
                value = Decimal(node[field])
                assert Decimal(0) <= value <= Decimal("99999.5")
                assert value * 2 == int(value * 2), "шаг 0,5 (BR-CALC-03)"
        if node["kind"] == "item":
            assert 1 <= node["multiplier"] <= 10_000
    for status in data["branch_status"]:
        assert status["status"] in BRANCH_STATUSES
        assert status["discipline_id"] in disciplines
    assert data["project"]["quote_figure"] in {"e", "p80", "p90"}
    assert Decimal("0") <= Decimal(data["project"]["pm_percent"]) <= Decimal("50")


def _money_blocks() -> list[tuple[str, dict, dict]]:
    blocks = []
    for figure, block in PORTAL["expected"]["money"]["by_figure"].items():
        blocks.append((f"portal-dilerov/{figure}", block, PORTAL["input"]["money"]))
    for case in EDGE["cases"]:
        money = case["expected"].get("money", {})
        for figure, block in money.get("by_figure", {}).items():
            blocks.append((f"{case['id']}/{figure}", block, case["input"]["money"]))
    return blocks


@pytest.mark.spec("BR-MONEY-04")
@pytest.mark.parametrize(
    ("block_id", "block", "money"), _money_blocks(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_money_rows_sum_to_totals(block_id: str, block: dict, money: dict) -> None:
    if "rows_rub" not in block:
        pytest.skip("частичный блок (переполнение)")
    rate = Decimal(money["exchange_rate"])
    rows_rub = {k: Decimal(v) for k, v in block["rows_rub"].items()}
    rows_cur = {k: Decimal(v) for k, v in block["rows_cur"].items()}
    assert set(rows_rub) == set(rows_cur)
    assert Decimal(block["total_rub"]) == sum(rows_rub.values()), "итог ₽ = сумма строк"
    for key, rub in rows_rub.items():
        assert rows_cur[key] == _round(rub / rate), f"{block_id}: строка {key} в валюте"
    assert Decimal(block["total_cur"]) == sum(rows_cur.values()), "итог в валюте = сумма строк"
    if money["vat_percent"] is None:
        for key in ("vat_rub", "total_with_vat_rub", "vat_cur", "total_with_vat_cur"):
            assert block[key] is None, f"{block_id}: {key} при «без НДС»"
    else:
        vat = _round(Decimal(block["total_rub"]) * Decimal(money["vat_percent"]) / 100)
        assert Decimal(block["vat_rub"]) == vat
        assert Decimal(block["total_with_vat_rub"]) == Decimal(block["total_rub"]) + vat
        assert Decimal(block["vat_cur"]) == _round(vat / rate)
        assert Decimal(block["total_with_vat_cur"]) == Decimal(block["total_cur"]) + Decimal(
            block["vat_cur"]
        )
    if money["currency"] == "RUB":
        assert rate == 1
        assert rows_rub == rows_cur


@pytest.mark.tc("TC-CALC-01")
@pytest.mark.tc("TC-MONEY-01")
def test_portal_quotes_spec_numbers() -> None:
    """Числа, которые SPEC 6.5 приводит дословно, на месте (защита от случайной правки фикстуры)."""
    exp = PORTAL["expected"]
    assert exp["total"]["values"]["e"] == "406.5"
    assert exp["total"]["values"]["p80"] == "425.5"
    assert exp["total"]["values"]["p90"] == "435.5"
    assert exp["works"]["values"]["sigma"] == "19.17"
    assert exp["pm"]["values"] == {
        "e": "62.0",
        "sigma": "3.5",
        "sigma_exact": "3.45",
        "base_e": "344.5",
    }
    money = exp["money"]["by_figure"]
    assert money["e"]["total_rub"] == "1146798"
    assert money["e"]["total_cur"] == "12397"
    assert exp["money"]["naive_total_cur_wrong"] == "12398"
    assert money["p80"]["k"] == "1.046823"
    assert money["p80"]["rows_rub"]["d-backend"] == "291017"
    assert money["p80"]["rows_cur"]["d-backend"] == "3146"
    assert money["p80"]["total_rub"] == "1200495"
    assert money["p80"]["total_with_vat_rub"] == "1440594"
    assert money["p80"]["total_with_vat_cur"] == "15574"
    assert money["p90"]["k"] == "1.071303"
    assert (money["p90"]["total_rub"], money["p90"]["total_with_vat_rub"]) == ("1228569", "1474283")
    assert money["p90"]["total_cur"] == "13282"


@pytest.mark.tc("TC-MONEY-01")
def test_quote_coefficients_match_totals() -> None:
    total = PORTAL["expected"]["total"]["values"]
    e = Decimal(total["e_precise"])
    p80 = Decimal(total["p80_precise"])
    assert _round(p80 / e, 6) == Decimal(PORTAL["expected"]["money"]["by_figure"]["p80"]["k"])


@pytest.mark.spec("BR-MONEY-04")
def test_overflow_case_exceeds_money_type() -> None:
    case = next(c for c in EDGE["cases"] if c["id"] == "money-overflow-currency")
    block = case["expected"]["money"]["by_figure"]["e"]
    assert Decimal(block["total_rub"]) < MONEY_LIMIT
    rate = Decimal(case["input"]["money"]["exchange_rate"])
    assert Decimal(block["total_rub"]) / rate >= MONEY_LIMIT
    assert block["total_cur"] is None


@pytest.mark.spec("BR-CALC-03")
@pytest.mark.parametrize(
    "item", EDGE["functions"]["round_half_up"]["cases"], ids=lambda c: f"{c['value']}@{c['places']}"
)
def test_round_half_up_table(item: dict) -> None:
    assert str(_round(Decimal(item["value"]), item["places"])) == item["expected"]


@pytest.mark.spec("BR-CALC-03")
def test_normalize_table_is_consistent() -> None:
    for item in EDGE["functions"]["normalize_hours"]["cases"]:
        if "error" in item:
            assert item["error"] in {"VALUE_OUT_OF_RANGE", "VALIDATION_FAILED"}
            continue
        raw = Decimal(item["input"].replace(",", "."))
        stepped = _round(raw * 2) / 2
        assert stepped == Decimal(item["expected"]), item
        assert item["rounded"] == (stepped != raw), item
