"""QA-017 · шаги сценариев денег (SPEC 17.2): G-03 «Эксперт открывает статистику», G-18 «Экспорт
для КП по P80». Строку «Стоимость» на экране проверяет Playwright (QA-018) — здесь ответ API, по
которому её нет.
"""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import load_workbook
from pytest_bdd import given, parsers, then, when
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli import seed_demo
from estimator.db.enums import SystemRole
from estimator.exports import engine
from tests.acceptance.steps.common import Scene, aio
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import _create, _setup

#: Части ключей с деньгами в ответах API (SEC-AUTHZ-04, TC-SEC-03): ``rate_rub``, ``cost_cur``…
MONEY_PARTS = {"rate", "rates", "cost", "costs", "currency", "exchange", "money", "vat", "price",
               "rub", "cur", "usd"}  # fmt: skip


def is_money_key(key: str) -> bool:
    return bool(MONEY_PARTS & set(key.lower().split("_")))


def money_paths(value: Any, path: str = "$") -> list[str]:
    """Пути денежных ключей и сумм в валюте во вложенном JSON."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if is_money_key(str(key)):
                found.append(f"{path}.{key}")
            found += money_paths(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += money_paths(item, f"{path}[{i}]")
    elif isinstance(value, str) and re.search(r"\b(USD|EUR|₽)\b", value):
        found.append(path)
    return found


def _amount(text: str) -> int:
    return int(re.sub(r"\s", "", text))


# --- G-03 ---------------------------------------------------------------------------------------


@given("в проекте заданы ставки и валюта USD")
@aio
async def rates_and_usd(world: World, db_session: AsyncSession, scene: Scene) -> None:
    s = scene.s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _create(s.backend_expert, s.pid, branch.id, title="Вход", o="8", r="12", p="20")
    assert leaf.status_code == 201, leaf.text
    money = await s.moderator.put(f"/projects/{s.pid}/money", json={
        "currency": "USD", "exchange_rate": "92.5",
        "rates": [{"discipline_id": str(s.backend), "rate_rub": "3000"},
                  {"discipline_id": None, "rate_rub": "2500"}],
    })  # fmt: skip
    assert money.status_code == 200, money.text
    assert money.json()["currency"] == "USD"


@when("эксперт открывает экран «Статистика»")
@aio
async def expert_opens_stats(scene: Scene) -> None:
    s = scene.s
    scene.responses["stats"] = await s.backend_expert.get(f"/projects/{s.pid}/stats")
    scene.responses["moderator"] = await s.moderator.get(f"/projects/{s.pid}/stats")


@then("на экране нет строки «Стоимость» и сумм в валюте")
def no_cost_line(scene: Scene) -> None:
    response = scene.responses["stats"]
    assert response.status_code == 200, response.text
    assert money_paths(response.json()) == [], money_paths(response.json())


@then("ответ API /stats не содержит денежных полей")
def stats_without_money(scene: Scene) -> None:
    assert "money" not in scene.responses["stats"].json()
    moderator = scene.responses["moderator"].json()
    assert "money" in moderator
    assert money_paths(moderator)


# --- G-18 ---------------------------------------------------------------------------------------


@given(parsers.parse(
    "проект из примера 6.5, «Цифра для КП» = {figure}, валюта {currency}, курс {rate}, НДС {vat}%"
))  # fmt: skip
@aio
async def portal_example(
    world: World, db_session: AsyncSession, scene: Scene, figure: str, currency: str, rate: str,
    vat: str,
) -> None:  # fmt: skip
    result = seed_demo.SeedResult()
    await seed_demo._check_dictionaries(db_session)
    users = await seed_demo._users(db_session, "demo-password-1", result)
    project = await seed_demo._portal(db_session, users)
    await db_session.flush()
    moderator = await world.session_for(users["demo.smirnova"].id, SystemRole.MODERATOR)
    body = (await moderator.get(f"/projects/{project.id}")).json()
    assert body.get("project", body)["quote_figure"] == figure.lower()
    money = (await moderator.get(f"/projects/{project.id}/money")).json()
    assert money["currency"] == currency
    assert float(money["exchange_rate"]) == float(rate.replace(",", "."))
    assert float(money["vat_percent"]) == float(vat)
    scene.data |= {"pid": project.id, "moderator": moderator}


@when("модератор выгружает Excel «С деньгами»")
@aio
async def money_export(db_session: AsyncSession, scene: Scene, export_queue: list[Any]) -> None:
    moderator, pid = scene.data["moderator"], scene.data["pid"]
    made = await moderator.post(f"/projects/{pid}/exports", json={"kind": "money_xlsx"})
    assert made.status_code == 202, made.text
    await deliver_events(db_session)
    [job] = [j for j in export_queue if str(j.export_id) == made.json()["id"]]
    await engine.run(db_session, job)
    ready = (await moderator.get(f"/exports/{made.json()['id']}")).json()
    got = await moderator.get(ready["download_url"].removeprefix("/api/v1"))
    assert got.status_code == 200, got.text
    sheet = load_workbook(io.BytesIO(got.content))["Для КП"]
    rows = [tuple(r) for r in sheet.iter_rows(values_only=True)]
    scene.data["quote"] = rows


def _line(scene: Scene, title: str) -> tuple[Any, ...]:
    return next(r for r in scene.data["quote"] if r and r[0] == title)


@then(parsers.re(
    r"на листе «Для КП» строка «(?P<title>[^»]+)» равна (?P<rub>[\d ]+) ₽ и (?P<usd>[\d ]+) USD"
))  # fmt: skip
def quote_line(scene: Scene, title: str, rub: str, usd: str) -> None:
    assert _line(scene, title)[2:4] == (_amount(rub), _amount(usd))


@then(parsers.re(
    r"итог без НДС равен (?P<rub>[\d ]+) ₽ и (?P<usd>[\d ]+) USD, а сумма строк равна итогу"
))  # fmt: skip
def quote_total(scene: Scene, rub: str, usd: str) -> None:
    total = _line(scene, "Итог без НДС")
    assert total[2:4] == (_amount(rub), _amount(usd))
    rows = scene.data["quote"]
    lines = rows[1 : rows.index(total)]
    assert sum(r[2] for r in lines if r and r[0]) == _amount(rub)


@then(parsers.re(r"итого с НДС равно (?P<rub>[\d ]+) ₽ и (?P<usd>[\d ]+) USD"))
def quote_with_vat(scene: Scene, rub: str, usd: str) -> None:
    assert _line(scene, "Итого с НДС")[2:4] == (_amount(rub), _amount(usd))
