"""EXP-011, EXP-012: документы заказчика — тип по сигнатуре, лимиты, шифрование на диске,
проверка антивирусом, «заражён», скачивание только чистого, корзина и восстановление
(FR-DOC-01, SEC-WEB-10, SEC-CRYPT-06, GAP-06, TC-SEC-10)."""

from __future__ import annotations

import datetime as dt
import io
import uuid
import zipfile
from typing import Any

import pytest
from docx import Document
from openpyxl import Workbook
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, ScanStatus
from estimator.db.models.files import CustomerDocument
from estimator.db.models.projects import Project
from estimator.documents import scan, service, storage, tasks, upload
from estimator.realtime.bus.memory import InMemoryBus
from tests.conftest import EICAR
from tests.integration.core.conftest import Actor, deliver_events
from tests.integration.core.test_customer_questions_api import _with_presale
from tests.integration.core.test_nodes_api import _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-DOC-01")]

PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n" + b"Smeta " * 2000 + b"\n%%EOF\n"


def _docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Техническое задание")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _xlsx() -> bytes:
    book = Workbook()
    book.active["A1"] = "Реестр"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _repack(
    source: bytes, *, types: tuple[str, str] | None = None, extra: str | None = None
) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item)
            if types and item.filename == "[Content_Types].xml":
                data = data.replace(types[0].encode(), types[1].encode())
            dst.writestr(item, data)
        if extra:
            dst.writestr(extra, b"\x00vba")
    return out.getvalue()


async def _upload(actor: Actor, pid: uuid.UUID, name: str, content: bytes) -> Any:
    return await actor.post(
        f"/projects/{pid}/documents", files={"file": (name, content, "application/octet-stream")}
    )


async def _audit(db: AsyncSession, object_id: str) -> list[tuple[str, dict[str, Any]]]:
    rows = await db.execute(
        text("SELECT event_type, details FROM audit.audit_log WHERE object_id = :o ORDER BY id"),
        {"o": object_id},
    )
    return [(r[0], r[1]) for r in rows]


@pytest.mark.spec("SEC-WEB-10")
@pytest.mark.spec("SEC-CRYPT-06")
@pytest.mark.tc("TC-SEC-10")
async def test_upload_scan_and_download(
    world: Any, db_session: AsyncSession, events: InMemoryBus, document_scans: list[uuid.UUID]
) -> None:
    s = await _setup(world, db_session)
    made = await _upload(s.moderator, s.pid, "ТЗ заказчика.pdf", PDF)
    assert made.status_code == 201, made.text
    doc = made.json()
    assert (doc["file_name"], doc["mime"], doc["size_bytes"], doc["scan_status"]) == (
        "ТЗ заказчика.pdf",
        upload.PDF,
        len(PDF),
        "pending",
    )
    assert (doc["uploaded_by"]["id"], doc["deleted_at"]) == (str(s.moderator.id), None)

    # на диске — UUID-имя и шифртекст, открытого текста нет
    row = await db_session.get(CustomerDocument, uuid.UUID(doc["id"]))
    assert row is not None
    stored = storage.path_of(row.storage_key)
    assert [p.name for p in storage.storage_dir().iterdir()] == [str(row.storage_key)]
    raw = stored.read_bytes()
    assert raw.startswith(b"ESTD")
    assert b"Smeta" not in raw
    assert b"%PDF" not in raw

    listed = (await s.backend_expert.get(f"/projects/{s.pid}/documents")).json()
    assert [d["id"] for d in listed["items"]] == [doc["id"]]
    assert (listed["used_bytes"], listed["limit_bytes"]) == (len(PDF), 1024**3)

    early = await s.backend_expert.get(f"/documents/{doc['id']}/download")
    assert (early.status_code, early.json()["code"]) == (409, "DOCUMENT_NOT_AVAILABLE")

    await deliver_events(db_session)
    assert document_scans == [uuid.UUID(doc["id"])]
    assert await tasks.check(db_session, uuid.UUID(doc["id"])) is ScanStatus.CLEAN
    assert await tasks.check(db_session, uuid.UUID(doc["id"])) is None  # уже проверен
    await deliver_events(db_session)
    scanned = [e for e in events.on(f"project:{s.pid}") if e["event"] == "document.scanned"]
    assert [e["data"] for e in scanned] == [{"document_id": doc["id"], "scan_status": "clean"}]

    got = await s.backend_expert.get(f"/documents/{doc['id']}/download")
    assert got.status_code == 200, got.text
    assert got.content == PDF
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-disposition"].startswith('attachment; filename="document.pdf"')
    assert "filename*=UTF-8''%D0%A2%D0%97" in got.headers["content-disposition"]
    assert got.headers["x-content-type-options"] == "nosniff"

    audit_rows = await _audit(db_session, doc["id"])
    assert [(e, d["op"]) for e, d in audit_rows] == [
        ("project.document.changed", "uploaded"),
        ("project.document.changed", "downloaded"),
    ]
    assert audit_rows[0][1]["size_bytes"] == len(PDF)

    # загружают только модератор и пресейл
    denied = await _upload(s.backend_expert, s.pid, "x.pdf", PDF)
    assert denied.status_code == 403
    presale = await _with_presale(world, s)
    assert (await _upload(presale, s.pid, "Реестр.xlsx", _xlsx())).json()["mime"] == upload.XLSX
    assert (await _upload(presale, s.pid, "ТЗ.docx", _docx())).json()["mime"] == upload.DOCX


@pytest.mark.spec("SEC-WEB-10")
@pytest.mark.spec("NFR-LIM-01")
@pytest.mark.tc("TC-SEC-10")
async def test_type_by_content_and_limits(
    world: Any, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session)
    docx, xlsx = _docx(), _xlsx()
    word_main = "wordprocessingml.document.main+xml"
    excel_main = "spreadsheetml.sheet.main+xml"
    rejected = {
        "setup.pdf": b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64,  # .exe под видом .pdf
        "macro.docx": _repack(
            docx,
            types=(
                f"openxmlformats-officedocument.{word_main}",
                "ms-word.document.macroEnabled.main+xml",
            ),
        ),
        "macro.xlsx": _repack(
            xlsx,
            types=(
                f"openxmlformats-officedocument.{excel_main}",
                "ms-excel.sheet.macroEnabled.main+xml",
            ),
        ),
        "vba.docx": _repack(docx, extra="word/vbaProject.bin"),
        "archive.docx": _repack(xlsx, types=(excel_main, "x-unknown+xml")),
        "notes.pdf": b"plain text, not a pdf",
        "broken.xlsx": b"PK\x03\x04garbage",
    }
    for name, content in rejected.items():
        got = await _upload(s.moderator, s.pid, name, content)
        assert (got.status_code, got.json()["code"]) == (415, "UNSUPPORTED_MEDIA_TYPE"), name

    # тип — по содержимому: PDF с расширением .docx принимается как PDF
    renamed = await _upload(s.moderator, s.pid, "на самом деле.docx", PDF)
    assert renamed.json()["mime"] == upload.PDF

    empty = await _upload(s.moderator, s.pid, "empty.pdf", b"")
    assert (empty.status_code, empty.json()["code"]) == (422, "VALIDATION_FAILED")

    monkeypatch.setattr(upload, "MAX_FILE_BYTES", len(PDF) - 1)
    big = await _upload(s.moderator, s.pid, "big.pdf", PDF)
    assert (big.status_code, big.json()["code"]) == (413, "PAYLOAD_TOO_LARGE")
    monkeypatch.setattr(upload, "MAX_FILE_BYTES", 50 * 1024 * 1024)

    monkeypatch.setattr(upload, "PROJECT_LIMIT_BYTES", 2 * len(PDF) - 1)
    full = await _upload(s.moderator, s.pid, "second.pdf", PDF)
    assert (full.status_code, full.json()["code"]) == (409, "PROJECT_STORAGE_LIMIT")
    assert full.json()["used_bytes"] == len(PDF)

    # отклонённые файлы не оставили следов на диске
    assert len(list(storage.storage_dir().iterdir())) == 1

    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ARCHIVED)
    )
    late = await _upload(s.moderator, s.pid, "late.pdf", PDF)
    assert (late.status_code, late.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")


def test_clean_name() -> None:
    assert upload.clean_name("C:\\Users\\a\\ТЗ.pdf") == "ТЗ.pdf"
    assert upload.clean_name("../../etc/passwd") == "passwd"
    assert upload.clean_name("a\x00b\nc.pdf") == "abc.pdf"
    assert upload.clean_name("   ") == ""
    long = upload.clean_name("я" * 300 + ".xlsx")
    assert (len(long), long.endswith(".xlsx")) == (255, True)
    assert len(upload.clean_name("я" * 300)) == 255


def test_parse_clamd_reply() -> None:
    assert scan.parse_reply(b"stream: OK\x00") == scan.Verdict(ScanStatus.CLEAN)
    assert scan.parse_reply(b"stream: Eicar-Test-Signature FOUND\x00") == scan.Verdict(
        ScanStatus.INFECTED, "Eicar-Test-Signature"
    )
    assert scan.parse_reply(b"INSTREAM size limit exceeded. ERROR\x00").status is ScanStatus.ERROR
    assert scan.parse_reply(b"").status is ScanStatus.ERROR


@pytest.mark.spec("SEC-WEB-10")
@pytest.mark.tc("TC-SEC-10")
async def test_infected_and_scan_errors(
    world: Any,
    db_session: AsyncSession,
    events: InMemoryBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await _setup(world, db_session)
    bad = (await _upload(s.moderator, s.pid, "virus.pdf", b"%PDF-1.4\n" + EICAR)).json()
    row = await db_session.get(CustomerDocument, uuid.UUID(bad["id"]))
    assert row is not None
    assert await tasks.check(db_session, row.id) is ScanStatus.INFECTED
    assert not storage.path_of(row.storage_key).exists()  # файл удалён

    listed = (await s.moderator.get(f"/projects/{s.pid}/documents")).json()
    assert [(d["id"], d["scan_status"]) for d in listed["items"]] == [(bad["id"], "infected")]
    assert listed["used_bytes"] == 0  # «заражён» место не занимает
    got = await s.moderator.get(f"/documents/{bad['id']}/download")
    assert (got.status_code, got.json()["code"]) == (409, "DOCUMENT_NOT_AVAILABLE")

    infected = [d for e, d in await _audit(db_session, bad["id"]) if e == "security.file_infected"]
    assert infected == [
        infected[0] | {"scan_status": "infected", "signature": "Eicar-Test-Signature"}
    ]
    assert infected[0]["mime"] == upload.PDF

    # clamd недоступен: задача повторяет, после последней попытки — «ошибка», файл удалён
    def down(_feed: Any) -> scan.Verdict:
        raise scan.ScannerUnavailable("connection refused")

    monkeypatch.setattr(scan, "scanner", down)
    other = (await _upload(s.moderator, s.pid, "ok.pdf", PDF)).json()
    other_id = uuid.UUID(other["id"])
    with pytest.raises(scan.ScannerUnavailable):
        await tasks.check(db_session, other_id, final=False)
    assert await tasks.check(db_session, other_id) is ScanStatus.ERROR
    await deliver_events(db_session)
    statuses = [
        e["data"]["scan_status"]
        for e in events.on(f"project:{s.pid}")
        if e["event"] == "document.scanned"
    ]
    assert statuses == ["infected", "error"]

    # строки отклонённых видны 24 часа, ночная задача их удаляет
    later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=25)
    assert (await service.list_documents(db_session, s.pid, now=later))["items"] == []
    assert await service.purge(db_session, now=later) == 2
    assert (await db_session.scalars(select(CustomerDocument.id))).all() == []


@pytest.mark.spec("GAP-06")
@pytest.mark.spec("FR-TREE-24")
async def test_trash_and_restore(
    world: Any, db_session: AsyncSession, events: InMemoryBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _setup(world, db_session)
    presale = await _with_presale(world, s)
    doc = (await _upload(presale, s.pid, "КП.docx", _docx())).json()
    doc_id = uuid.UUID(doc["id"])
    await tasks.check(db_session, doc_id)

    assert (await s.backend_expert.delete(f"/documents/{doc['id']}")).status_code == 403
    gone = await presale.delete(f"/documents/{doc['id']}")
    assert gone.status_code == 204, gone.text
    assert (await presale.delete(f"/documents/{doc['id']}")).status_code == 204  # повтор
    listed = (await s.moderator.get(f"/projects/{s.pid}/documents")).json()
    assert (listed["items"], listed["used_bytes"]) == ([], 0)
    hidden = await s.backend_expert.get(f"/documents/{doc['id']}/download")
    assert hidden.status_code == 404

    # корзину с документами видят модератор и пресейл (пресейл — только документы), эксперт — нет
    for actor in (s.moderator, presale):
        trash = await actor.get(f"/projects/{s.pid}/trash")
        assert trash.status_code == 200, trash.text
        [item] = trash.json()["items"]
        assert (item["kind"], item["batch_id"], item["root_title"]) == (
            "document",
            doc["id"],
            "КП.docx",
        )
        assert item["document"]["deleted_at"] is not None
        assert item["deleted_by"]["id"] == str(presale.id)
    expert_trash = await s.backend_expert.get(f"/projects/{s.pid}/trash")
    assert expert_trash.json()["items"] == []
    assert (await s.backend_expert.post(f"/documents/{doc['id']}/restore")).status_code == 403

    # восстановление снова проверяет место проекта
    monkeypatch.setattr(upload, "PROJECT_LIMIT_BYTES", 10)
    full = await presale.post(f"/documents/{doc['id']}/restore")
    assert (full.status_code, full.json()["code"]) == (409, "PROJECT_STORAGE_LIMIT")
    monkeypatch.setattr(upload, "PROJECT_LIMIT_BYTES", 1024**3)
    back = await presale.post(f"/documents/{doc['id']}/restore")
    assert back.status_code == 200, back.text
    assert (back.json()["deleted_at"], back.json()["scan_status"]) == (None, "clean")
    assert (await s.backend_expert.get(f"/documents/{doc['id']}/download")).status_code == 200
    ops = [
        d["op"] for e, d in await _audit(db_session, doc["id"]) if e == "project.document.changed"
    ]
    assert ops == ["uploaded", "deleted", "restored", "downloaded"]

    # «Завершена» — только чтение (D-01), скачивать можно
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.COMPLETED)
    )
    late = await s.moderator.delete(f"/documents/{doc['id']}")
    assert (late.status_code, late.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")
    assert (await s.moderator.get(f"/documents/{doc['id']}/download")).status_code == 200

    # через 30 дней в корзине ночная задача удаляет файл и строку
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ESTIMATION)
    )
    assert (await s.moderator.delete(f"/documents/{doc['id']}")).status_code == 204
    row = await db_session.get(CustomerDocument, doc_id)
    assert row is not None
    path = storage.path_of(row.storage_key)
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=29)
    assert await service.purge(db_session, now=soon) == 0
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=31)
    assert await service.purge(db_session, now=later) == 1
    assert not path.exists()
    assert await db_session.get(CustomerDocument, doc_id) is None
    ops = [
        d["op"] for e, d in await _audit(db_session, doc["id"]) if e == "project.document.changed"
    ]
    assert ops[-1] == "purged"
