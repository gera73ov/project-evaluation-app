"""EXP-013 · скорость выгрузки Excel «С деньгами» (NFR-PERF-05): проект на 2 000 узлов
строится не дольше 10 секунд.

Проект — «Нагрузочный тест (2 000 узлов)» из демо-данных (``estimator seed-demo``), со ставками
дисциплин и валютой КП. Замер — построение файла фоновой задачей (``engine.run``): ровно то, что
делает воркер Celery. Окончательный замер — на стенде stage (PLAN.md EXP-013).
"""

from __future__ import annotations

import io
import time
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli import seed_demo
from estimator.db.enums import SystemRole
from estimator.db.models.tree import Node
from estimator.exports import engine
from tests.integration.core.conftest import World, deliver_events

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-PERF-05")]

#: NFR-PERF-05: экспорт Excel для 2 000 узлов — не дольше 10 секунд.
LIMIT_SECONDS = 10.0


async def test_money_export_of_2000_nodes_within_limit(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    db = db_session
    await seed_demo._check_dictionaries(db)
    users = await seed_demo._users(db, "demo-password-1", seed_demo.SeedResult())
    project = await seed_demo._load_project(db, users)
    await db.flush()
    live = await db.scalar(
        select(func.count()).where(Node.project_id == project.id, Node.deleted_at.is_(None))
    )
    assert live == seed_demo.LOAD_NODES == 2000

    moderator = await world.session_for(users["demo.ivanov"].id, SystemRole.MODERATOR)
    disciplines = (
        await db.scalars(select(Node.discipline_id).where(Node.project_id == project.id).distinct())
    ).all()
    money = await moderator.put(f"/projects/{project.id}/money", json={
        "currency": "USD", "exchange_rate": "92.5",
        "rates": [{"discipline_id": str(d), "rate_rub": "3000"} for d in disciplines if d]
        + [{"discipline_id": None, "rate_rub": "2500"}],
    })  # fmt: skip
    assert money.status_code == 200, money.text

    made = await moderator.post(f"/projects/{project.id}/exports", json={"kind": "money_xlsx"})
    assert made.status_code == 202, made.text
    await deliver_events(db)
    [job] = [j for j in export_queue if str(j.export_id) == made.json()["id"]]

    started = time.perf_counter()
    await engine.run(db, job)
    elapsed = time.perf_counter() - started

    ready = (await moderator.get(f"/exports/{made.json()['id']}")).json()
    assert ready["status"] == "ready", ready
    got = await moderator.get(ready["download_url"].removeprefix("/api/v1"))
    book = load_workbook(io.BytesIO(got.content), read_only=True)
    assert book["Оценка"].max_row > seed_demo.LOAD_NODES
    print(f"EXP-013: «С деньгами» на {live} узлах — {elapsed:.2f} с")
    assert elapsed <= LIMIT_SECONDS, f"{elapsed:.2f} с > {LIMIT_SECONDS} с (NFR-PERF-05)"
