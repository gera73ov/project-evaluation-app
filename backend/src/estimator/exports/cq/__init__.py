"""EXP-007 · вопросы заказчику в Excel и Word (FR-CQ-02, FR-CQ-04, 11.11 №2 и №7, FR-EXP-06;
contracts/exports.yaml ``cq_xlsx``, ``cq_docx``).

Выбранные вопросы (FE по умолчанию отмечает все «новые») в порядке номера В-NNN: шапка «Проект,
Заказчик, Дата выгрузки», таблица «№, Раздел, Вопрос, Ответ» с пустой колонкой ответа. Снятые
вопросы в файл не попадают. Денег, автора, статуса, обсуждений и закрытых заметок в файле нет.

После построения выгруженные «новые» становятся «отправлен» с датой
(:func:`estimator.services.customer_questions.flow.mark_sent`) в той же транзакции: не удалась
выгрузка — статусы не меняются.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

from docx import Document
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import CustomerQuestionStatus
from estimator.db.models.discussions import Message, Thread
from estimator.db.models.projects import Project
from estimator.exports import engine, marks
from estimator.exports.safe_values import as_text, write_cell
from estimator.exports.source import today
from estimator.exports.xlsx_hours import BOLD, finish
from estimator.services.customer_questions import flow
from estimator.services.customer_questions.listing import node_paths

HEADER = ("№", "Раздел", "Вопрос", "Ответ")


@dataclass(frozen=True)
class Row:
    thread_id: uuid.UUID
    number: str
    section: str
    question: str


async def rows(db: AsyncSession, project_id: uuid.UUID, thread_ids: list[uuid.UUID]) -> list[Row]:
    threads = (
        await db.scalars(
            select(Thread)
            .where(
                Thread.project_id == project_id,
                Thread.id.in_(thread_ids),
                Thread.is_customer,
                Thread.customer_status != CustomerQuestionStatus.WITHDRAWN,
            )
            .order_by(Thread.customer_question_no)
        )
    ).all()
    firsts: dict[uuid.UUID | None, Message] = {}
    for m in (
        await db.scalars(
            select(Message)
            .where(Message.thread_id.in_([t.id for t in threads]), Message.needs_answer)
            .order_by(Message.created_at, Message.id)
        )
    ).all():
        firsts.setdefault(m.thread_id, m)
    paths = await node_paths(db, project_id, {t.node_id for t in threads if t.node_id})
    out = []
    for t in threads:
        first = firsts.get(t.id)
        body = "" if first is None or first.revoked_at is not None else first.body
        section = " › ".join(paths.get(t.node_id, [])) if t.node_id else "Проект"
        out.append(Row(t.id, f"В-{t.customer_question_no:03d}", section, body))
    return out


def xlsx(project: Project, items: list[Row], mark: marks.Mark) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Вопросы"
    head = [
        ("Проект", project.name),
        ("Заказчик", project.customer or ""),
        ("Дата выгрузки", mark.local_time),
    ]
    start = marks.XLSX_DATA_ROW
    for i, (name, value) in enumerate(head):
        write_cell(sheet.cell(row=start + i, column=1), name).font = BOLD
        write_cell(sheet.cell(row=start + i, column=2), value)
    row = start + len(head) + 1
    for col, name in enumerate(HEADER, start=1):
        write_cell(sheet.cell(row=row, column=col), name).font = BOLD
    for item in items:
        row += 1
        for col, value in enumerate((item.number, item.section, item.question, None), start=1):
            write_cell(sheet.cell(row=row, column=col), value)
    for col, width in zip("ABCD", (8, 40, 70, 50), strict=True):
        sheet.column_dimensions[col].width = width
    return finish(book, mark)


def docx(project: Project, items: list[Row], mark: marks.Mark) -> bytes:
    document = Document()
    document.add_heading("Вопросы заказчику", level=1)
    document.add_paragraph(f"Проект: {as_text(project.name)}")
    document.add_paragraph(f"Заказчик: {as_text(project.customer or '')}")
    document.add_paragraph(f"Дата: {mark.local_time}")
    table = document.add_table(rows=1, cols=len(HEADER))
    table.style = "Table Grid"
    for cell, name in zip(table.rows[0].cells, HEADER, strict=True):
        cell.text = name
    for item in items:
        cells = table.add_row().cells
        for cell, value in zip(cells, (item.number, item.section, item.question, ""), strict=True):
            cell.text = value  # как текст, без разметки (SEC-WEB-02)
    marks.apply_docx(document, mark)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


async def _build(db: AsyncSession, job: engine.Job, mark: marks.Mark, fmt: str) -> engine.Built:
    if job.project_id is None:  # pragma: no cover — вид всегда проектный
        raise ValueError("вопросы заказчику без проекта")
    project = await db.get(Project, job.project_id)
    if project is None:
        raise ValueError("проект удалён")
    ids = [uuid.UUID(str(t)) for t in job.params.get("thread_ids", [])]
    items = await rows(db, project.id, ids)
    content = xlsx(project, items, mark) if fmt == "xlsx" else docx(project, items, mark)
    principal = await engine.job_principal(db, job)
    await flow.mark_sent(db, principal, project.id, [i.thread_id for i in items])
    name = marks.file_name(project.name, today(mark.moment, mark.timezone), "вопросы", fmt)
    return engine.Built(content, name, len(items))


@engine.register("cq_xlsx")
async def build_xlsx(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    return await _build(db, job, mark, "xlsx")


@engine.register("cq_docx")
async def build_docx(db: AsyncSession, job: engine.Job, mark: marks.Mark) -> engine.Built:
    return await _build(db, job, mark, "docx")
