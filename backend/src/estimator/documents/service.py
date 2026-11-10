"""Документы заказчика: приём, список, скачивание, корзина, ночная очистка (EXP-011, EXP-012;
SPEC FR-DOC-01, 11.7 №1–6, SEC-WEB-10, GAP-06, FR-TREE-24).

* Занятое место — живые (не в корзине) документы ``pending`` и ``clean``; документы в корзине
  место не занимают, поэтому восстановление снова проверяет лимит 1 ГБ.
* «Заражён» и «ошибка проверки» — файла уже нет, строка видна в списке 24 часа (11.7 №3),
  ночная задача удаляет её.
* Скачивание — только ``clean`` (иначе 409 ``DOCUMENT_NOT_AVAILABLE``), каждое — в аудит.
* Удалённый документ живёт в корзине 30 дней (Q-04), затем ночная задача удаляет файл и строку.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import uuid
from typing import Any, BinaryIO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ScanStatus
from estimator.db.models.files import CustomerDocument
from estimator.db.models.projects import Project
from estimator.documents import storage, upload
from estimator.security import audit
from estimator.services.discussions import feed

RETENTION = dt.timedelta(days=30)  # корзина, Q-04
REJECTED_VISIBLE = dt.timedelta(hours=24)  # строка «заражён», 11.7 №3
_OCCUPYING = (ScanStatus.PENDING, ScanStatus.CLEAN)
_REJECTED = (ScanStatus.INFECTED, ScanStatus.ERROR)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def documents_out(db: AsyncSession, docs: list[CustomerDocument]) -> list[dict[str, Any]]:
    users = await feed.user_refs(db, {d.uploaded_by for d in docs})
    return [
        {
            "id": d.id,
            "file_name": d.file_name,
            "mime": d.mime,
            "size_bytes": d.size_bytes,
            "scan_status": str(d.scan_status),
            "uploaded_by": users[d.uploaded_by],
            "uploaded_at": feed.ts(d.uploaded_at),
            "deleted_at": feed.ts(d.deleted_at),
        }
        for d in docs
    ]


async def used_bytes(db: AsyncSession, project_id: uuid.UUID) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(CustomerDocument.size_bytes), 0)).where(
            CustomerDocument.project_id == project_id,
            CustomerDocument.deleted_at.is_(None),
            CustomerDocument.scan_status.in_(_OCCUPYING),
        )
    )
    return int(total or 0)


async def list_documents(
    db: AsyncSession, project_id: uuid.UUID, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Вкладка «Документы заказчика»: живые документы, новые сверху, и занятое место."""
    moment = now or _now()
    docs = (
        await db.scalars(
            select(CustomerDocument)
            .where(
                CustomerDocument.project_id == project_id,
                CustomerDocument.deleted_at.is_(None),
            )
            .order_by(CustomerDocument.uploaded_at.desc(), CustomerDocument.id)
        )
    ).all()
    visible = [
        d
        for d in docs
        if d.scan_status not in _REJECTED or d.uploaded_at > moment - REJECTED_VISIBLE
    ]
    return {
        "items": await documents_out(db, visible),
        "used_bytes": await used_bytes(db, project_id),
        "limit_bytes": upload.PROJECT_LIMIT_BYTES,
    }


def _audit_details(doc: CustomerDocument, op: str) -> dict[str, Any]:
    return {
        "op": op,
        "mime": doc.mime,
        "size_bytes": doc.size_bytes,
        "scan_status": str(doc.scan_status),
    }


async def _audit(db: AsyncSession, principal: Principal, doc: CustomerDocument, op: str) -> None:
    await audit.write(
        db,
        "project.document.changed",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="document",
        object_id=doc.id,
        project_id=doc.project_id,
        details=_audit_details(doc, op),
    )


async def _check_room(db: AsyncSession, project_id: uuid.UUID, size: int) -> None:
    # Строка проекта под блокировкой: параллельные загрузки считают место по очереди
    await db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    used = await used_bytes(db, project_id)
    if used + size > upload.PROJECT_LIMIT_BYTES:
        raise ApiError(
            "PROJECT_STORAGE_LIMIT",
            detail="Место проекта закончилось: документы заняли бы больше 1 ГБ",
            used_bytes=used,
            limit_bytes=upload.PROJECT_LIMIT_BYTES,
        )


async def create(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    file_name: str | None,
    src: BinaryIO,
) -> CustomerDocument:
    """Принять файл: размер, имя, тип по сигнатуре, место проекта; зашифровать в карантин.

    Проверку антивирусом ставит :func:`estimator.documents.tasks.enqueue` после commit.
    """
    size = upload.size_of(src)
    if size > upload.MAX_FILE_BYTES:
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            detail="Файл больше 50 МБ",
            limit_bytes=upload.MAX_FILE_BYTES,
        )
    if size == 0:
        raise _invalid("file", "файл пустой")
    name = upload.clean_name(file_name)
    if not name:
        raise _invalid("file", "у файла нет имени")
    try:
        mime = upload.detect(src)
    except upload.UnsupportedType as exc:
        raise ApiError(
            "UNSUPPORTED_MEDIA_TYPE",
            detail=f"Можно загрузить только PDF, DOCX или XLSX без макросов: {exc}",
        ) from None
    await _check_room(db, project_id, size)
    doc_id, storage_key = uuid.uuid4(), uuid.uuid4()
    key_enc = await asyncio.to_thread(storage.write_encrypted, src, doc_id, storage_key)
    doc = CustomerDocument(
        id=doc_id,
        project_id=project_id,
        file_name=name,
        mime=mime,
        size_bytes=size,
        storage_key=storage_key,
        key_enc=key_enc,
        scan_status=ScanStatus.PENDING,
        uploaded_by=principal.user_id,
        uploaded_at=_now(),
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(doc)
    try:
        await db.flush()
    except Exception:
        storage.remove(storage_key)
        raise
    _remove_on_rollback(db, storage_key)
    await _audit(db, principal, doc, "uploaded")
    return doc


def _remove_on_rollback(db: AsyncSession, storage_key: uuid.UUID) -> None:
    from sqlalchemy import event

    def drop(_session: object, previous: Any) -> None:
        if getattr(previous, "parent", None) is None:  # откат всей транзакции, не точки сохранения
            storage.remove(storage_key)

    event.listen(db.sync_session, "after_soft_rollback", drop, once=True)

    def keep(_session: object) -> None:
        if event.contains(db.sync_session, "after_soft_rollback", drop):
            event.remove(db.sync_session, "after_soft_rollback", drop)

    event.listen(db.sync_session, "after_commit", keep, once=True)


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


async def locked(db: AsyncSession, document_id: uuid.UUID) -> CustomerDocument:
    doc = await db.scalar(
        select(CustomerDocument).where(CustomerDocument.id == document_id).with_for_update()
    )
    if doc is None:  # pragma: no cover — gate уже ответил 404
        raise ApiError("NOT_FOUND")
    return doc


async def download(
    db: AsyncSession, principal: Principal, doc: CustomerDocument
) -> tuple[bytes, CustomerDocument]:
    """Расшифрованный файл ``clean``-документа и аудит скачивания (SEC-WEB-10)."""
    if doc.deleted_at is not None:
        raise ApiError("NOT_FOUND", detail="Документ в корзине")
    if doc.scan_status is not ScanStatus.CLEAN:
        raise ApiError(
            "DOCUMENT_NOT_AVAILABLE",
            detail=(
                "Документ ещё проверяется антивирусом"
                if doc.scan_status is ScanStatus.PENDING
                else "Документ не прошёл проверку антивирусом"
            ),
            scan_status=str(doc.scan_status),
        )
    buffer = io.BytesIO()
    try:
        await asyncio.to_thread(
            storage.read_decrypted, buffer, doc.id, doc.storage_key, doc.key_enc
        )
    except FileNotFoundError:
        raise ApiError("DOCUMENT_NOT_AVAILABLE", detail="Файла документа нет на диске") from None
    await _audit(db, principal, doc, "downloaded")
    return buffer.getvalue(), doc


async def delete(db: AsyncSession, principal: Principal, doc: CustomerDocument) -> None:
    """В корзину на 30 дней; отклонённый антивирусом (файла уже нет) — сразу совсем."""
    if doc.deleted_at is not None:
        return
    if doc.scan_status in _REJECTED:
        await _audit(db, principal, doc, "deleted")
        await db.delete(doc)
        return
    doc.deleted_at = _now()
    doc.deleted_by = principal.user_id
    doc.updated_by = principal.user_id
    await _audit(db, principal, doc, "deleted")


async def restore(db: AsyncSession, principal: Principal, doc: CustomerDocument) -> None:
    """Вернуть из корзины (GAP-06): лимит места проверяется заново; запись в аудит."""
    if doc.deleted_at is None:
        return
    await _check_room(db, doc.project_id, doc.size_bytes)
    doc.deleted_at = None
    doc.deleted_by = None
    doc.updated_by = principal.user_id
    await _audit(db, principal, doc, "restored")


async def trash_items(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Удалённые документы для ``GET /projects/{id}/trash`` (элементы ``kind = document``)."""
    docs = (
        await db.scalars(
            select(CustomerDocument).where(
                CustomerDocument.project_id == project_id,
                CustomerDocument.deleted_at.is_not(None),
            )
        )
    ).all()
    if not docs:
        return []
    out = await documents_out(db, list(docs))
    deleters = await feed.user_refs(db, {d.deleted_by for d in docs if d.deleted_by})
    items = []
    for doc, item in zip(docs, out, strict=True):
        deleted_at = doc.deleted_at
        if deleted_at is None:  # pragma: no cover — отобраны только удалённые
            continue
        items.append(
            {
                "batch_id": str(doc.id),
                "kind": "document",
                "root_title": doc.file_name,
                "nodes_count": 0,
                "discipline_id": None,
                "deleted_at": feed.ts(deleted_at),
                "deleted_by": deleters.get(doc.deleted_by) if doc.deleted_by else None,
                "purge_at": feed.ts(deleted_at + RETENTION),
                "document": {**item, "id": str(item["id"])},
            }
        )
    return items


async def purge(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Ночная очистка: корзина старше 30 дней (файл и строка, аудит ``purged``) и строки
    «заражён»/«ошибка» старше 24 часов. Число удалённых строк."""
    moment = now or _now()
    expired = (
        await db.scalars(
            select(CustomerDocument).where(
                CustomerDocument.deleted_at.is_not(None),
                CustomerDocument.deleted_at < moment - RETENTION,
            )
        )
    ).all()
    rejected = (
        await db.scalars(
            select(CustomerDocument).where(
                CustomerDocument.deleted_at.is_(None),
                CustomerDocument.scan_status.in_(_REJECTED),
                CustomerDocument.uploaded_at < moment - REJECTED_VISIBLE,
            )
        )
    ).all()
    for doc in expired:
        await audit.write(
            db,
            "project.document.changed",
            actor="system",
            object_type="document",
            object_id=doc.id,
            project_id=doc.project_id,
            details=_audit_details(doc, "purged"),
        )
    for doc in [*expired, *rejected]:
        storage.remove(doc.storage_key)
        await db.delete(doc)
    await db.flush()
    return len(expired) + len(rejected)
