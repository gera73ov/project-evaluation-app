"""EXP-007: вопросы заказчику в Excel и Word — состав файла, «новые» → «отправлен», права."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from docx import Document
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.exports import engine
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_customer_questions_api import _ask, _status, _with_presale
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [
    pytest.mark.integration,
    pytest.mark.spec("FR-CQ-02"),
    pytest.mark.spec("FR-CQ-04"),
]


async def _file(db: AsyncSession, queue: list[Any], actor: Any, export_id: str) -> bytes:
    await deliver_events(db)
    [job] = [j for j in queue if str(j.export_id) == export_id]
    await engine.run(db, job)
    ready = (await actor.get(f"/exports/{export_id}")).json()
    assert ready["status"] == "ready"
    got = await actor.get(ready["download_url"].removeprefix("/api/v1"))
    assert got.status_code == 200, got.text
    return got.content


async def test_cq_export(world: World, db_session: AsyncSession, export_queue: list[Any]) -> None:
    s = await _setup(world, db_session)
    presale = await _with_presale(world, s)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Обмен с 1С", o="40", r="60", p="100")
    q1 = await _ask(s.backend_expert, leaf["id"], "=HYPERLINK(1) протокол?")
    q2 = await _ask(s.backend_expert, leaf["id"], "Формат?")
    await s.moderator.post(f"/nodes/{leaf['id']}/messages", json={"body": "внутреннее обсуждение"})
    url = f"/projects/{s.pid}/customer-questions/export"
    ids = [q1["thread_id"], q2["thread_id"]]

    denied = await s.backend_expert.post(url, json={"thread_ids": ids, "format": "xlsx"})
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    alien = await presale.post(url, json={"thread_ids": [str(uuid.uuid4())], "format": "xlsx"})
    assert (alien.status_code, alien.json()["code"]) == (422, "VALIDATION_FAILED")

    made = await presale.post(url, json={"thread_ids": ids[:1], "format": "xlsx"})
    assert made.status_code == 202, made.text
    assert made.json()["kind"] == "cq_xlsx"
    assert await _status(db_session, q1["thread_id"]) == "new"  # до построения не меняется
    content = await _file(db_session, export_queue, presale, made.json()["id"])
    sheet = load_workbook(io.BytesIO(content))["Вопросы"]
    rows = [r for r in sheet.iter_rows(values_only=True) if any(r)]
    assert rows[0][0] == "Коммерческая тайна"
    table = rows[rows.index(("№", "Раздел", "Вопрос", "Ответ")) + 1 :]
    assert len(table) == 1
    number, section, question, answer = table[0]
    assert (number, answer) == ("В-001", None)
    assert section.endswith("Обмен с 1С")
    assert question == "'=HYPERLINK(1) протокол?"  # экранировано (EXP-002)
    assert "внутреннее" not in str(rows)
    assert await _status(db_session, q1["thread_id"]) == "sent"
    assert await _status(db_session, q2["thread_id"]) == "new"

    word = await presale.post(url, json={"thread_ids": ids, "format": "docx"})
    assert word.status_code == 202, word.text
    doc = Document(io.BytesIO(await _file(db_session, export_queue, presale, word.json()["id"])))
    assert doc.paragraphs[0].text.startswith("Коммерческая тайна")
    cells = [[c.text for c in r.cells] for r in doc.tables[0].rows]
    assert [c[0] for c in cells] == ["№", "В-001", "В-002"]
    assert cells[2][2] == "Формат?"
    assert await _status(db_session, q2["thread_id"]) == "sent"
