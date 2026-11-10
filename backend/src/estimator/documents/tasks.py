"""Проверка документа антивирусом задачей Celery и итог проверки (EXP-011; SPEC SEC-WEB-10,
15.4 ``document.scanned``).

* ``clean`` — документ можно скачивать;
* ``infected`` — файл удаляется, строка «заражён» видна 24 часа, аудит ``security.file_infected``
  с оповещением ИБ (уходит и в SIEM вместе с журналом);
* ``error`` — проверка не прошла (``clamd`` ответил ошибкой или недоступен после всех повторов):
  файл не выдаётся и удаляется так же, как заражённый (SEC-WEB-10 «заражённый или непроверенный
  файл не выдаётся и удаляется»).

Событие ``document.scanned`` уходит в канал проекта. О документе, который за время проверки
уже убрали в корзину, событие не шлётся: фильтр WS не знает о корзине, а удалённые документы
видят только модератор и пресейл (GAP-06) — им статус покажет корзина.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ScanStatus
from estimator.db.models.files import CustomerDocument
from estimator.db.session import after_commit
from estimator.documents import scan, service, storage
from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger
from estimator.realtime.bus import publish
from estimator.security import audit

log = get_logger(__name__)

SCAN_TASK = "estimator.documents.scan"
PURGE_TASK = "estimator.documents.purge"
MAX_RETRIES = 5
RETRY_SECONDS = 60


async def _enqueue(document_id: uuid.UUID) -> None:  # pragma: no cover — нужен брокер Celery
    scan_document.apply_async((str(document_id),))


#: Постановка проверки; тесты подменяют её записью в очередь и запускают :func:`check` сами.
dispatch: Callable[[uuid.UUID], Awaitable[None]] = _enqueue


def enqueue(db: AsyncSession, document_id: uuid.UUID) -> None:
    """Поставить проверку после commit (файл и строка уже записаны)."""

    async def hook() -> None:
        try:
            await dispatch(document_id)
        except Exception as exc:  # noqa: BLE001 — документ останется pending, его видно в списке
            log.warning(
                "document_scan_enqueue_failed", document_id=str(document_id), error=str(exc)
            )

    after_commit(db, hook)


def _verdict(doc: CustomerDocument) -> scan.Verdict:
    def feed(sink: scan.Sink) -> None:
        storage.read_decrypted(sink, doc.id, doc.storage_key, doc.key_enc)  # type: ignore[arg-type]

    return scan.scanner(feed)


async def check(
    db: AsyncSession, document_id: uuid.UUID, *, final: bool = True
) -> ScanStatus | None:
    """Проверить документ ``pending`` и записать итог; ``None`` — проверять нечего.

    ``clamd`` недоступен: при ``final=False`` — :class:`scan.ScannerUnavailable` (задача повторит),
    при ``final=True`` — итог ``error``.
    """
    doc = await db.scalar(
        select(CustomerDocument).where(CustomerDocument.id == document_id).with_for_update()
    )
    if doc is None or doc.scan_status is not ScanStatus.PENDING:
        return None
    try:
        verdict = await asyncio.to_thread(_verdict, doc)
    except FileNotFoundError:
        verdict = scan.Verdict(ScanStatus.ERROR)
    except scan.ScannerUnavailable:
        if not final:
            raise
        log.error("document_scan_unavailable", document_id=str(document_id))
        verdict = scan.Verdict(ScanStatus.ERROR)
    doc.scan_status = verdict.status
    if verdict.status is not ScanStatus.CLEAN:
        storage.remove(doc.storage_key)
        await audit.write(
            db,
            "security.file_infected",
            "failure",
            actor="system",
            object_type="document",
            object_id=doc.id,
            project_id=doc.project_id,
            details={
                "scan_status": str(verdict.status),
                "signature": verdict.signature,
                "mime": doc.mime,
                "size_bytes": doc.size_bytes,
            },
            alert=True,
        )
    if doc.deleted_at is None:
        publish(
            db,
            f"project:{doc.project_id}",
            "document.scanned",
            {"document_id": str(doc.id), "scan_status": str(verdict.status)},
        )
    return verdict.status


async def _session_run(work: Callable[[AsyncSession], Awaitable[Any]]) -> Any:  # pragma: no cover
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.config import get_settings
    from estimator.db.session import create_engine, transaction

    engine = create_engine(get_settings())  # свой движок: у asyncio.run свой цикл событий
    try:
        # transaction — commit и хуки after-commit (событие document.scanned, оповещение ИБ)
        async with transaction(async_sessionmaker(engine)) as db:
            return await work(db)
    finally:
        await engine.dispose()


@shared_task(bind=True, name=SCAN_TASK, max_retries=MAX_RETRIES)
def scan_document(self: Any, document_id: str) -> str | None:  # pragma: no cover — в worker
    final = self.request.retries >= MAX_RETRIES
    try:
        status = asyncio.run(
            _session_run(lambda db: check(db, uuid.UUID(document_id), final=final))
        )
    except scan.ScannerUnavailable as exc:
        raise self.retry(exc=exc, countdown=RETRY_SECONDS * (self.request.retries + 1)) from exc
    return str(status) if status else None


@shared_task(name=PURGE_TASK)
def purge_documents() -> int:  # pragma: no cover — запуск в worker
    return int(asyncio.run(_session_run(service.purge)))


register_periodic(PeriodicTask("documents_purge", PURGE_TASK, crontab(hour=2, minute=45)))
