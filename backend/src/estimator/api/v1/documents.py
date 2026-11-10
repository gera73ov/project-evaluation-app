"""Документы заказчика (EXP-011, EXP-012; contracts/openapi.yaml ``listDocuments``,
``uploadDocument``, ``downloadDocument``, ``deleteDocument``, ``restoreDocument``).

Объект ``/documents/{id}`` для gate — проект документа (:func:`document_target`), поэтому
загрузку, удаление и восстановление в «Завершён» и «Архив» отклоняет общий гейт статусов
(D-01). Логика — :mod:`estimator.documents.service`, проверка антивирусом —
:mod:`estimator.documents.tasks`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import File, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.files import CustomerDocument
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.documents import service, tasks
from estimator.security.authz.deps import register_resolver
from estimator.security.authz.engine import Target

router = ApiRouter(tags=["Проекты"])

_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


async def document_target(db: AsyncSession, document_id: uuid.UUID) -> Target | None:
    row = (
        await db.execute(
            select(CustomerDocument.project_id, Project.status)
            .join(Project, Project.id == CustomerDocument.project_id)
            .where(CustomerDocument.id == document_id)
        )
    ).first()
    if row is None:
        return None
    return Target(project_id=row[0], project_status=str(row[1]), kind="document")


register_resolver("/documents/{id}", document_target)


async def _one(db: AsyncSession, doc: CustomerDocument) -> dict[str, Any]:
    [out] = await service.documents_out(db, [doc])
    return out


@router.get(
    "/projects/{id}/documents",
    permission="docs.read",
    response_model=s.DocumentList,
    response_model_exclude_unset=True,
)
async def list_documents(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    """Вкладка «Документы заказчика» (11.7): файлы, статус проверки, место из 1 ГБ."""
    return await service.list_documents(db, id)


@router.post(
    "/projects/{id}/documents",
    permission="docs.write",
    status_code=201,
    response_model=s.DocumentOut,
    response_model_exclude_unset=True,
)
async def upload_document(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Загрузить PDF, DOCX или XLSX до 50 МБ; проверка антивирусом — после ответа."""
    doc = await service.create(db, principal, id, file.filename, file.file)
    tasks.enqueue(db, doc.id)
    return await _one(db, doc)


@router.get(
    "/documents/{id}/download",
    permission="docs.read",
    response_class=Response,
)
async def download_document(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> Response:
    """Файл ``clean``-документа как вложение (SEC-WEB-10); каждое скачивание — в аудит."""
    content, doc = await service.download(db, principal, await service.locked(db, id))
    ext = _EXT.get(doc.mime, "")
    disposition = f"attachment; filename=\"document{ext}\"; filename*=UTF-8''{quote(doc.file_name)}"
    return Response(
        content,
        media_type="application/octet-stream",  # контракт; вид файла — по имени
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/documents/{id}", permission="docs.write", status_code=204)
async def delete_document(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> Response:
    """В корзину проекта на 30 дней (FR-DOC-01)."""
    await service.delete(db, principal, await service.locked(db, id))
    return Response(status_code=204)


@router.post(
    "/documents/{id}/restore",
    permission="docs.restore",
    response_model=s.DocumentOut,
    response_model_exclude_unset=True,
)
async def restore_document(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    """Вернуть из корзины модератором или пресейлом проекта (GAP-06), с аудитом."""
    doc = await service.locked(db, id)
    await service.restore(db, principal, doc)
    return await _one(db, doc)
