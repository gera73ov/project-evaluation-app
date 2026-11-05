"""EXP-001: contracts/exports.yaml описывает все выгрузки SPEC и их права."""

from __future__ import annotations

import pytest

from tests.unit._contracts import load_yaml

pytestmark = [pytest.mark.spec("FR-EXP-01"), pytest.mark.spec("FR-EXP-06")]

E = load_yaml("exports.yaml")
P = load_yaml("permissions.yaml")
AUD = load_yaml("audit-events.yaml")
KINDS: dict = E["kinds"]


def _sheet(kind: str, name: str) -> dict:
    return next(s for s in KINDS[kind]["sheets"] if s["name"] == name)


def test_kinds_from_plan():
    assert set(KINDS) == {
        "hours_xlsx", "money_xlsx", "cq_xlsx", "cq_docx", "snapshot_diff_xlsx",
        "stats_tab_xlsx", "assumptions_docx", "portfolio_xlsx", "audit_csv",
    }  # fmt: skip


def test_permissions_exist_and_money_kinds_are_totp_gated():
    for name, k in KINDS.items():
        perm = P["permissions"][k["permission"]]
        if k["money_only"]:
            assert perm.get("totp_gate") is True, name


def test_fr_exp_01_columns_in_order():
    cols = [c["name"] for c in _sheet("hours_xlsx", "Оценка")["columns"]]
    assert cols == ["Уровень", "Узел", "Тип", "×N", "O", "R", "P", "E", "σ", "Комментарий",
                    "Метка", "Статус ветки", "Проверено"]  # fmt: skip
    names = [s["name"] for s in KINDS["hours_xlsx"]["sheets"]]
    assert names == ["Оценка", "Допущения и риски", "Параметры"]


def test_fr_exp_02_money_sheets():
    extra = [c["name"] for c in _sheet("money_xlsx", "Оценка")["extra_columns"]]
    assert extra == ["Ставка", "Стоимость, ₽", "Стоимость, <валюта КП>"]
    assert [s["name"] for s in KINDS["money_xlsx"]["sheets"]] == [
        "Оценка", "Для КП", "Допущения и риски", "Параметры",
    ]  # fmt: skip
    block = _sheet("money_xlsx", "Для КП")["comparison_block"]
    assert block["rows"] == ["E", "P80", "P90"]


def test_hours_export_has_no_money_columns():
    for sheet in KINDS["hours_xlsx"]["sheets"]:
        for col in sheet["columns"]:
            assert not col.get("money"), col
            assert "₽" not in col["name"], col


def test_cq_export_has_customer_columns_only():
    cols = [c["name"] for c in _sheet("cq_xlsx", "Вопросы")["columns"]]
    assert cols == ["№", "Раздел", "Вопрос", "Ответ"]
    assert KINDS["cq_docx"]["table"][:3] == ["№", "Раздел", "Вопрос"]


def test_marks_and_formula_escaping():
    common = E["common"]
    assert "Коммерческая тайна" in common["marks"]["text"]
    assert common["marks"]["csv"].startswith("Первая строка-комментарий «# Коммерческая тайна;")
    escaping = " ".join(common["values"])
    for ch in ("«=»", "«+»", "«-»", "«@»"):
        assert ch in escaping
    assert common["delivery"]["retention_hours"] == 24
    for ev in common["delivery"]["audit"]:
        assert ev in AUD["events"]
    assert "audit.exported" in AUD["events"]


def test_file_name_pattern_fr_exp_03():
    assert E["common"]["file_name"]["pattern"].startswith("<Название проекта>_<снимок или дата>_")
    assert KINDS["hours_xlsx"]["file_name"]["kind_part"] == "часы"
    assert KINDS["money_xlsx"]["file_name"]["kind_part"] == "деньги"
