"""EXP-003…006: фоновые выгрузки «Часы» и «С деньгами» — постановка, построение, статус,
скачивание только запросившим, срок 24 часа, аудит; состав файла на «Портале дилеров» (6.5,
G-18), выгрузка из снимка."""

from __future__ import annotations

import datetime as dt
import io
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from openpyxl import load_workbook
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli import seed_demo
from estimator.db.enums import SystemRole
from estimator.db.models.files import ExportFile
from estimator.db.models.tree import Node
from estimator.db.models.users import User
from estimator.exports import engine
from tests.integration.core.conftest import Actor, World, deliver_events

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-EXP-05")]


async def _portal(world: World, db: AsyncSession) -> tuple[uuid.UUID, Actor]:
    result = seed_demo.SeedResult()
    await seed_demo._check_dictionaries(db)
    users = await seed_demo._users(db, "demo-password-1", result)
    project = await seed_demo._portal(db, users)
    await db.flush()
    moderator = await world.session_for(users["demo.smirnova"].id, SystemRole.MODERATOR)
    return project.id, moderator


async def _built(db: AsyncSession, queue: list[Any], actor: Actor, export_id: str) -> Any:
    await deliver_events(db)
    [job] = [j for j in queue if str(j.export_id) == export_id]
    await engine.run(db, job)
    ready = await actor.get(f"/exports/{export_id}")
    assert ready.status_code == 200, ready.text
    return ready.json()


async def _book(actor: Actor, job: dict[str, Any]):  # type: ignore[no-untyped-def]
    got = await actor.get(job["download_url"].removeprefix("/api/v1"))
    assert got.status_code == 200, got.text
    assert got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff"
    return load_workbook(io.BytesIO(got.content))


async def _join_expert(moderator: Actor, pid: uuid.UUID, expert: Actor) -> Actor:
    team = (await moderator.get(f"/projects/{pid}/members")).json()["items"]
    members = [
        {"user_id": m["user"]["id"], "role": m["role"], "discipline_id": m["discipline_id"]}
        for m in team
    ]
    discipline = next(m["discipline_id"] for m in team if m["discipline_id"])
    members.append({"user_id": str(expert.id), "role": "expert", "discipline_id": discipline})
    put = await moderator.put(f"/projects/{pid}/members", json={"members": members})
    assert put.status_code == 200, put.text
    return expert


def _stored() -> list[Path]:
    return list(Path(engine.storage_dir()).iterdir())


def _rows(sheet: Any) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in sheet.iter_rows(values_only=True)]


def _by_title(rows: list[tuple[Any, ...]], title: str) -> tuple[Any, ...]:
    return next(r for r in rows if r[1] == title)


@pytest.mark.spec("FR-EXP-01")
@pytest.mark.spec("FR-EXP-06")
@pytest.mark.spec("TC-SEC-04")
async def test_hours_export(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    pid, moderator = await _portal(world, db_session)
    url = f"/projects/{pid}/exports"

    made = await moderator.post(url, json={"kind": "hours_xlsx"})
    assert made.status_code == 202, made.text
    assert (made.json()["status"], made.json()["download_url"]) == ("pending", None)
    job = await _built(db_session, export_queue, moderator, made.json()["id"])
    assert job["status"] == "ready"
    assert job["file_name"].startswith("Портал дилеров_")
    assert job["file_name"].endswith("_часы.xlsx")

    # чужой пользователь — 404, даже модератор проекта
    other = await world.session_for(
        await db_session.scalar(select(User.id).where(User.login == "demo.ivanov")),
        SystemRole.MODERATOR,
    )
    foreign = await other.get(f"/exports/{job['id']}")
    assert (foreign.status_code, foreign.json()["code"]) == (404, "NOT_FOUND")

    book = await _book(moderator, job)
    assert book.sheetnames == ["Оценка", "Допущения и риски", "Параметры"]
    sheet = book["Оценка"]
    assert sheet["A1"].value == "Коммерческая тайна"
    assert "Коммерческая тайна" in sheet.oddHeader.center.text
    rows = _rows(sheet)
    header = rows[4]
    assert header[:9] == ("Уровень", "Узел", "Тип", "×N", "O", "R", "P", "E", "σ")
    assert not {"Ставка", "Стоимость, ₽"} & set(header)  # денег в «Часах» нет
    e_col = header.index("E")
    total = {r[1]: r[e_col] for r in rows if r[1] in ("Итог E", "P80", "P90")}
    assert {k: Decimal(str(v)) for k, v in total.items()} == {
        "Итог E": Decimal("406.5"),
        "P80": Decimal("425.5"),
        "P90": Decimal("435.5"),
    }
    assert any(r[1] == "Цифра для КП: P80" for r in rows)
    params = dict(_rows(book["Параметры"])[1:])
    assert params["Проект"] == "Портал дилеров"
    assert params["Кто выгрузил"] == "Смирнова Анна"

    audit = (
        await db_session.execute(
            text(
                "SELECT event_type, details FROM audit.audit_log WHERE object_id = :o ORDER BY id"
            ),
            {"o": job["id"]},
        )
    ).all()
    assert [a[0] for a in audit] == ["export.created", "export.downloaded"]
    assert audit[0][1]["with_money"] is False
    assert audit[0][1]["rows"] > 10

    # срок вышел — 410, ночная очистка удаляет строку и файл
    await db_session.execute(
        update(ExportFile)
        .where(ExportFile.id == uuid.UUID(job["id"]))
        .values(expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
    )
    gone = await moderator.get(f"/exports/{job['id']}")
    assert (gone.status_code, gone.json()["code"]) == (410, "EXPORT_EXPIRED")
    assert len(_stored()) == 1
    assert await engine.cleanup(db_session) == 1
    assert _stored() == []


@pytest.mark.spec("FR-EXP-02")
@pytest.mark.spec("BR-MONEY-04")
@pytest.mark.spec("TC-MONEY-01")
async def test_money_export(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    pid, moderator = await _portal(world, db_session)
    url = f"/projects/{pid}/exports"
    no_totp = await world.session_for(moderator.id, SystemRole.MODERATOR, mfa=False)
    blocked = await no_totp.post(url, json={"kind": "money_xlsx"})
    assert (blocked.status_code, blocked.json()["code"]) == (403, "TOTP_REQUIRED")

    made = await moderator.post(url, json={"kind": "money_xlsx"})
    assert made.status_code == 202, made.text
    job = await _built(db_session, export_queue, moderator, made.json()["id"])
    assert job["file_name"].endswith("_деньги.xlsx")
    book = await _book(moderator, job)
    assert book.sheetnames == ["Оценка", "Для КП", "Допущения и риски", "Параметры"]

    header = _rows(book["Оценка"])[4]
    assert {"Ставка", "Стоимость, ₽", "Стоимость, USD"} <= set(header)

    quote = _rows(book["Для КП"])
    assert quote[0][:4] == ("Строка", "По E, ₽", "Для КП (P80), ₽", "Для КП, USD")
    lines = {r[0]: r for r in quote if r and r[0]}
    assert lines["Бэкенд"][2:4] == (291017, 3146)
    assert lines["Итог без НДС"][2:4] == (1200495, 12978)
    assert lines["Итого с НДС"][2:4] == (1440594, 15574)
    rows_rub = [r[2] for r in quote[1 : quote.index(lines["Итог без НДС"])]]
    assert sum(rows_rub) == 1200495  # суммы столбцов сходятся с итогом
    params = dict(_rows(book["Параметры"])[1:])
    assert (params["Валюта КП"], params["Ставка НДС"]) == ("USD", "20 %")


async def test_expert_and_snapshot_export(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    pid, moderator = await _portal(world, db_session)
    expert = await _join_expert(moderator, pid, await world.actor())
    url = f"/projects/{pid}/exports"

    denied = await expert.post(url, json={"kind": "money_xlsx"})
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    allowed = await expert.post(url, json={"kind": "hours_xlsx"})
    assert allowed.status_code == 202, allowed.text

    snap = await moderator.post(f"/projects/{pid}/snapshots", json={"name": "Версия 1"})
    assert snap.status_code == 201, snap.text
    sid = snap.json()["id"]
    leaf = await db_session.scalar(
        select(Node).where(Node.project_id == pid, Node.o.is_not(None)).limit(1)
    )
    leaf.p = (leaf.p or Decimal(0)) + Decimal(100)  # type: ignore[union-attr]
    await db_session.flush()

    made = await moderator.post(url, json={"kind": "hours_xlsx", "snapshot_id": sid})
    assert made.status_code == 202, made.text
    job = await _built(db_session, export_queue, moderator, made.json()["id"])
    assert "_Версия 1_часы" in job["file_name"]
    rows = _rows((await _book(moderator, job))["Оценка"])
    e_col = rows[4].index("E")
    assert Decimal(str(_by_title(rows, "Итог E")[e_col])) == Decimal("406.5")

    wrong = await moderator.post(url, json={"kind": "hours_xlsx", "snapshot_id": str(uuid.uuid4())})
    assert (wrong.status_code, wrong.json()["code"]) == (422, "VALIDATION_FAILED")


@pytest.mark.spec("FR-SNAP-05")
async def test_diff_export(world: World, db_session: AsyncSession, export_queue: list[Any]) -> None:
    pid, moderator = await _portal(world, db_session)
    expert = await _join_expert(moderator, pid, await world.actor())
    snap = await moderator.post(f"/projects/{pid}/snapshots", json={"name": "До правок"})
    assert snap.status_code == 201, snap.text
    sid = snap.json()["id"]
    leaf = await db_session.scalar(
        select(Node).where(Node.project_id == pid, Node.o.is_not(None)).limit(1)
    )
    leaf.p = (leaf.p or Decimal(0)) + Decimal(100)  # type: ignore[union-attr]
    await db_session.flush()
    url = f"/snapshots/{sid}/diff/export"

    bad = await moderator.post(url, json={"with": "вчера"})
    assert (bad.status_code, bad.json()["code"]) == (422, "VALIDATION_FAILED")

    made = await moderator.post(url, json={"with": "current"})
    assert made.status_code == 202, made.text
    job = await _built(db_session, export_queue, moderator, made.json()["id"])
    assert "_До правок — Текущее состояние_сравнение" in job["file_name"]
    book = await _book(moderator, job)
    assert book.sheetnames == ["Сводка", "Изменения"]
    summary = {r[0]: r for r in _rows(book["Сводка"]) if r and r[0]}
    assert "«в КП», ₽" in summary
    changes = _rows(book["Изменения"])
    assert "Δ, ₽" in changes[0]
    assert [r[0] for r in changes[1:]] == ["изменён", "параметр проекта"]  # узел и пересчёт УП
    assert changes[1][3] == "P"

    plain = await expert.post(url, json={"with": "current"})
    assert plain.status_code == 202, plain.text
    job = await _built(db_session, export_queue, expert, plain.json()["id"])
    book = await _book(expert, job)
    assert "«в КП», ₽" not in {r[0] for r in _rows(book["Сводка"])}
    assert "Δ, ₽" not in _rows(book["Изменения"])[0]


@pytest.mark.spec("FR-EXP-06")
async def test_stats_and_assumptions_export(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    pid, moderator = await _portal(world, db_session)
    expert = await _join_expert(moderator, pid, await world.actor())
    tabs = ["readiness", "totals", "ratios", "volumes", "candidates", "tags", "discussions",
            "customer_questions", "reviewed", "snapshots", "dynamics"]  # fmt: skip
    for tab in tabs:
        made = await moderator.get(f"/projects/{pid}/stats/{tab}/export", params={"format": "xlsx"})
        assert made.status_code == 202, (tab, made.text)
        job = await _built(db_session, export_queue, moderator, made.json()["id"])
        assert job["file_name"].endswith(".xlsx"), tab
        book = await _book(moderator, job)
        assert book.worksheets[0]["A1"].value == "Коммерческая тайна"
        if tab == "totals":
            assert book.sheetnames == ["Итоги", "Сумма для КП"]
            head = _rows(book["Итоги"])[4]
            assert "Стоимость, ₽" in head

    made = await expert.get(f"/projects/{pid}/stats/totals/export", params={"format": "xlsx"})
    job = await _built(db_session, export_queue, expert, made.json()["id"])
    book = await _book(expert, job)
    assert book.sheetnames == ["Итоги"]
    assert "Стоимость, ₽" not in _rows(book["Итоги"])[4]

    denied = await expert.get(f"/projects/{pid}/assumptions/export")
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    made = await moderator.get(f"/projects/{pid}/assumptions/export")
    assert made.status_code == 202, made.text
    job = await _built(db_session, export_queue, moderator, made.json()["id"])
    assert job["file_name"].endswith("_допущения.docx")
    got = await moderator.get(job["download_url"].removeprefix("/api/v1"))
    doc = Document(io.BytesIO(got.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert text.startswith("Коммерческая тайна")
    assert "Обоснование процента управления проектом" in text


@pytest.mark.spec("FR-PORT-02")
async def test_portfolio_export(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    pid, moderator = await _portal(world, db_session)
    today = dt.date.today()
    body = {"from": (today - dt.timedelta(days=30)).isoformat(), "to": today.isoformat()}
    denied = await moderator.post("/portfolio/export", json=body)
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    head = await world.actor(SystemRole.PRESALE_HEAD)
    wrong = await head.post("/portfolio/export", json={"from": body["to"], "to": body["from"]})
    assert (wrong.status_code, wrong.json()["code"]) == (422, "VALIDATION_FAILED")
    made = await head.post("/portfolio/export", json=body)
    assert made.status_code == 202, made.text
    job = await _built(db_session, export_queue, head, made.json()["id"])
    assert job["file_name"].startswith("Портфель_")
    book = await _book(head, job)
    assert book.sheetnames == ["Реестр", "Сводка", "Параметры"]
    names = [r[0] for r in _rows(book["Реестр"])[5:]]
    assert "Портал дилеров" in names
    assert pid
