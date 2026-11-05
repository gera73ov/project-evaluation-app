"""DB-004, DB-010: ограничения справочников и данные по умолчанию после ``estimator migrate``."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from estimator.db.models.settings import SystemSetting
from tests.integration.db.test_users_constraints import _rejects

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5")]

SETTINGS_SCHEMA = Path(__file__).resolve().parents[4] / "contracts" / "settings.schema.json"


async def test_second_cross_cutting_phase_rejected(db_session: AsyncSession) -> None:
    await _rejects(db_session, Phase(name="Ещё сквозная", sort_order=99, is_cross_cutting=True))


@pytest.mark.spec("BR-MONEY-05")
async def test_second_default_vat_rejected(db_session: AsyncSession) -> None:
    await _rejects(db_session, VatRate(name="13%", percent=Decimal(13), is_default=True))


async def test_rub_cannot_be_disabled(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                update(Currency).where(Currency.code == "RUB").values(is_active=False)
            )


async def test_work_type_is_single_and_cannot_be_disabled(db_session: AsyncSession) -> None:
    await _rejects(db_session, NodeType(name="Работа 2", icon="work", is_system=True))
    await _rejects(
        db_session, NodeType(name="Сломанный", icon="work", is_system=True, is_active=False)
    )


async def test_local_type_needs_project_status(db_session: AsyncSession) -> None:
    # глобальный тип не может быть «предложенным» (proposed — только у локального)
    await _rejects(db_session, NodeType(name="Локальный", icon="api", proposal_status="proposed"))


@pytest.mark.spec("2")
async def test_default_phases(db_session: AsyncSession) -> None:
    rows = (await db_session.scalars(select(Phase).order_by(Phase.sort_order))).all()
    assert [(p.name, p.is_cross_cutting) for p in rows] == [
        ("Анализ и проектирование", False),
        ("Разработка", False),
        ("Тестирование", False),
        ("Внедрение", False),
        ("Гарантийная поддержка", False),
        ("Управление проектом", True),
    ]


@pytest.mark.spec("5.2")
async def test_default_node_types_match_spec_5_2(db_session: AsyncSession) -> None:
    rows = {t.name: t for t in (await db_session.scalars(select(NodeType))).all()}
    expected_icons = {
        "Модуль": "module",
        "Функция": "function",
        "Экран": "screen",
        "Интеграция": "integration",
        "Отчёт": "report",
        "Сущность": "entity",
        "Сервис": "service",
        "Тест-набор": "test_suite",
        "Документ": "document",
        "Работа": "work",
    }
    assert {n: t.icon for n, t in rows.items()} == expected_icons
    assert [n["label"] + " " + "-".join((n["o"], n["r"], n["p"])) for n in rows["Экран"].norms] == [
        "простой 2-4-6",
        "средний 5-7-10",
        "сложный 12-16-24",
    ]
    assert rows["Тест-набор"].norms == [{"label": "на кейс", "o": "0.5", "r": "1", "p": "2"}]
    assert rows["Модуль"].norms == []
    assert [n for n, t in rows.items() if t.is_system] == ["Работа"]


@pytest.mark.spec("FR-TREE-04")
async def test_default_profiles_match_spec_5_2(db_session: AsyncSession) -> None:
    types = {t.id: t.name for t in (await db_session.scalars(select(NodeType))).all()}
    profiles = (await db_session.scalars(select(DisciplineProfile))).all()
    discs = {d.id: d for d in (await db_session.scalars(select(Discipline))).all()}
    by_disc: dict[str, set[str]] = {}
    defaults: dict[str, str] = {}
    for p in profiles:
        chain = " → ".join(types[t] for t in p.type_chain)
        disc = discs[p.discipline_id]
        by_disc.setdefault(disc.name, set()).add(chain)
        if disc.default_profile_id == p.id:
            defaults[disc.name] = chain
    assert defaults == {
        "Бэкенд": "Модуль → Функция",
        "Фронтенд": "Экран",
        "Аналитика": "Документ",
        "QA": "Тест-набор",
        "Архитектура": "Работа",
        "DevOps": "Работа",
    }
    assert by_disc["Бэкенд"] == {"Модуль → Функция", "Сервис → Функция", "Функция"}
    assert by_disc["QA"] == {"Тест-набор", "Функция", "Экран"}
    assert all(len(d.short_name) <= 12 for d in discs.values())


@pytest.mark.spec("BR-MONEY-03")
async def test_default_money_dictionaries(db_session: AsyncSession) -> None:
    codes = set((await db_session.scalars(select(Currency.code))).all())
    assert codes == {"RUB", "USD", "EUR", "CNY", "KZT", "BYN", "AED"}
    vat = (await db_session.scalars(select(VatRate))).all()
    assert sorted((v.percent is None, v.percent or 0) for v in vat) == sorted(
        [(True, 0)] + [(False, Decimal(p)) for p in (0, 5, 7, 10, 20, 22)]
    )
    assert [v.percent for v in vat if v.is_default] == [Decimal("22.00")]


@pytest.mark.spec("BR-PRJ-05")
async def test_default_loss_reasons_and_tags(db_session: AsyncSession) -> None:
    reasons = {r.name: r.is_other for r in (await db_session.scalars(select(LossReason))).all()}
    assert reasons == {
        "Цена": False,
        "Сроки": False,
        "Выбран конкурент": False,
        "Отказ от проекта": False,
        "Другое": True,
    }
    tags = {t.short_name: t.category for t in (await db_session.scalars(select(CommentTag))).all()}
    assert tags == {
        "Огр.": "constraint",
        "Тех.": "tech",
        "Риск": "risk",
        "Допущение": "assumption",
    }


@pytest.mark.spec("6.6")
async def test_default_control_ratio(db_session: AsyncSession) -> None:
    discs = {d.id: d.name for d in (await db_session.scalars(select(Discipline))).all()}
    (ratio,) = (await db_session.scalars(select(ControlRatio))).all()
    assert discs[ratio.discipline_a_id] == "QA"
    assert {discs[d] for d in ratio.disciplines_b} == {"Бэкенд", "Фронтенд"}
    assert (ratio.min_pct, ratio.max_pct) == (Decimal(25), Decimal(35))


@pytest.mark.spec("BR-PRJ-03")
async def test_method_settings_match_contract_defaults(db_session: AsyncSession) -> None:
    schema = json.loads(SETTINGS_SCHEMA.read_text(encoding="utf-8"))["properties"]
    rows = (
        await db_session.scalars(select(SystemSetting).where(SystemSetting.key.like("method.%")))
    ).all()
    expected = {k: v["default"] for k, v in schema.items() if k.startswith("method.")}
    assert {r.key: r.value for r in rows} == expected
