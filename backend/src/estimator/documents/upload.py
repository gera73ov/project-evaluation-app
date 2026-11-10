"""Приём документа заказчика (EXP-011; SPEC FR-DOC-01, SEC-WEB-10, NFR-LIM-01).

Тип определяется по содержимому, а не по расширению: PDF — по сигнатуре ``%PDF-``; DOCX и
XLSX — ZIP-пакет OOXML, у которого в ``[Content_Types].xml`` главная часть документа Word или
книги Excel. Пакеты с макросами (главная часть ``macroEnabled``, ``vbaProject.bin``) и шаблоны
отклоняются — это 415 ``UNSUPPORTED_MEDIA_TYPE``.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from typing import BinaryIO

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

MAX_FILE_BYTES = 50 * 1024 * 1024  # FR-DOC-01, NFR-LIM-01
PROJECT_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 ГБ на проект
MAX_NAME = 255

_MAIN_PARTS = {
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
}
_MACRO_MARKERS = (
    "macroenabled",
    "application/vnd.ms-office.vbaproject",
)
_CONTENT_TYPES_MAX = 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UnsupportedType(Exception):
    """Содержимое не PDF, DOCX или XLSX либо файл с макросами."""


def _ooxml(src: BinaryIO) -> str:
    try:
        with zipfile.ZipFile(src) as pack:
            names = pack.namelist()
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise UnsupportedType("файл с макросами")
            info = pack.getinfo("[Content_Types].xml")
            if info.file_size > _CONTENT_TYPES_MAX:
                raise UnsupportedType("повреждённый пакет OOXML")
            types = pack.read(info).decode("utf-8", "replace").lower()
    except (zipfile.BadZipFile, KeyError, EOFError, ValueError) as exc:
        raise UnsupportedType("не документ Word или Excel") from exc
    if any(marker in types for marker in _MACRO_MARKERS):
        raise UnsupportedType("файл с макросами")
    found = [mime for mime, part in _MAIN_PARTS.items() if f'contenttype="{part}"' in types]
    if len(found) != 1:
        raise UnsupportedType("не документ Word или Excel")
    return found[0]


def detect(src: BinaryIO) -> str:
    """MIME документа по содержимому; иначе :class:`UnsupportedType`."""
    src.seek(0)
    head = src.read(8)
    src.seek(0)
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        return _ooxml(src)
    raise UnsupportedType("разрешены только PDF, DOCX и XLSX")


def size_of(src: BinaryIO) -> int:
    src.seek(0, 2)
    size = src.tell()
    src.seek(0)
    return size


def clean_name(raw: str | None) -> str:
    """Имя для показа: без пути и управляющих символов, до 255 символов; пусто — ``""``."""
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()
    if len(name) > MAX_NAME:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: MAX_NAME - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_NAME]
    return name
