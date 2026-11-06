"""EXP-002 · отметки «Коммерческая тайна» и имя файла выгрузки (FR-EXP-06, FR-EXP-03, Q-36).

Отметка — гриф, ФИО выгрузившего и дата со временем в его часовом поясе (users.timezone, иначе
app.timezone, FR-UI-02). Где она стоит (contracts/exports.yaml, common.marks):

* xlsx — верхний и нижний колонтитулы каждого листа и строки 1–3 первого листа; данные
  первого листа начинаются со строки :data:`XLSX_DATA_ROW`;
* docx — колонтитулы каждой страницы (каждого раздела) и первый абзац документа;
* csv — первая строка-комментарий ``# Коммерческая тайна; <ФИО>; <дата и время>``.

Имя файла (:func:`file_name`) — ``<Название проекта>_<снимок или дата>_<вид>.<расширение>``:
недопустимые символы и управляющие → ``_``, повторы ``_`` схлопываются, до 150 символов без
расширения за счёт названия проекта.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from docx.document import Document as DocxDocument
from openpyxl.workbook.workbook import Workbook

from estimator.exports.safe_values import write_cell

GRIF = "Коммерческая тайна"
XLSX_DATA_ROW = 5
FILE_NAME_MAX = 150
_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_UNDERSCORES = re.compile(r"_{2,}")


@dataclass(frozen=True)
class Mark:
    """Отметка выгрузки: кто и когда (момент — с поясом, выводится в ``timezone``)."""

    full_name: str
    moment: datetime
    timezone: str = "Europe/Moscow"

    @property
    def local_time(self) -> str:
        moment = self.moment if self.moment.tzinfo else self.moment.replace(tzinfo=UTC)
        return moment.astimezone(ZoneInfo(self.timezone)).strftime("%d.%m.%Y %H:%M")

    @property
    def text(self) -> str:
        """``Коммерческая тайна · <ФИО> · <ДД.ММ.ГГГГ ЧЧ:ММ>``."""
        return f"{GRIF} · {self.full_name} · {self.local_time}"

    @property
    def csv_comment(self) -> str:
        """``# Коммерческая тайна; <ФИО>; <ДД.ММ.ГГГГ ЧЧ:ММ>``."""
        return f"# {GRIF}; {self.full_name}; {self.local_time}"


def _header_text(text: str) -> str:
    # «&» в колонтитуле Excel — управляющий символ
    return text.replace("&", "&&")


def apply_xlsx(workbook: Workbook, mark: Mark) -> None:
    """Колонтитулы всех листов и строки 1–3 первого листа (данные — со строки 5)."""
    text = _header_text(mark.text)
    for sheet in workbook.worksheets:
        for header in (sheet.oddHeader, sheet.evenHeader, sheet.firstHeader):
            header.center.text = text
        for footer in (sheet.oddFooter, sheet.evenFooter, sheet.firstFooter):
            footer.center.text = text
    first = workbook.worksheets[0]
    write_cell(first.cell(row=1, column=1), GRIF)
    write_cell(first.cell(row=2, column=1), mark.full_name)
    write_cell(first.cell(row=3, column=1), mark.local_time)


def apply_docx(document: DocxDocument, mark: Mark) -> None:
    """Колонтитулы каждого раздела и первый абзац документа."""
    for section in document.sections:
        for part in (section.header, section.footer):
            part.is_linked_to_previous = False
            paragraph = part.paragraphs[0] if part.paragraphs else part.add_paragraph()
            paragraph.text = mark.text
    paragraphs = document.paragraphs
    if paragraphs:
        paragraphs[0].insert_paragraph_before(mark.text)
    else:
        document.add_paragraph(mark.text)


def clean_part(text: str) -> str:
    """Часть имени файла: недопустимые и управляющие символы → ``_``, повторы схлопнуты."""
    cleaned = _UNDERSCORES.sub("_", _INVALID.sub("_", text.strip()))
    return cleaned.strip(" .") or "_"


def file_name(project: str, source: str | date, kind_part: str, ext: str) -> str:
    """``<проект>_<снимок или ДД.ММ.ГГГГ>_<вид>.<ext>``; длина без расширения ≤ 150."""
    middle = source.strftime("%d.%m.%Y") if isinstance(source, date) else clean_part(source)
    tail = f"_{middle}_{clean_part(kind_part)}"
    room = max(FILE_NAME_MAX - len(tail), 1)
    head = clean_part(project)[:room].rstrip(" ._") or "_"
    name = _UNDERSCORES.sub("_", f"{head}{tail}")[:FILE_NAME_MAX]
    return f"{name}.{ext.lstrip('.')}"
