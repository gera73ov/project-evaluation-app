"""CORE-090 · физическое удаление проекта (SPEC BR-PRJ-04, GAP-12, SEC-AUD-01, 18.2).

Выполняет служба эксплуатации командой ``estimator project purge`` по заявке, согласованной с ИБ.
Удаляется строка ``projects``: дерево, история, ``change_log``, обсуждения, заметки, снимки,
журнал, итоги, деньги, команда, уведомления, записи документов и экспортов уходят каскадом
(все ключи на проект — ``ON DELETE CASCADE``, G-12). Файлы документов заказчика (вместе с ними
пропадают и зашифрованные ключи данных — они в строках ``customer_documents``) и файлы
экспортов удаляются с томов после commit. Записи аудита остаются: в них нет содержимого оценки.

Каждый запуск — событие ``project.purged`` (номер заявки, логин согласовавшего, состав,
``dry_run``) с пользователем ОС; аудит уходит в SIEM обычным порядком.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.discussions import Message, ProjectNote, Thread
from estimator.db.models.files import CustomerDocument, ExportFile, Snapshot
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.security import audit

TICKET_MAX = 100
LOGIN_MAX = 100


class PurgeError(Exception):
    """Отказ команды: нет проекта, пустые обязательные аргументы."""


@dataclass
class Composition:
    """Состав удаляемого (GAP-12): число записей по видам."""

    nodes: int = 0
    threads: int = 0
    messages: int = 0
    notes: int = 0
    snapshots: int = 0
    documents: int = 0
    exports: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class PurgePlan:
    project_id: uuid.UUID
    project_name: str
    composition: Composition
    document_keys: list[uuid.UUID] = field(default_factory=list)
    export_files: list[str] = field(default_factory=list)


async def _count(db: AsyncSession, model: type[Any], *where: ColumnElement[bool]) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def plan(db: AsyncSession, project_id: uuid.UUID) -> PurgePlan:
    """Состав удаляемого без изменений (dry-run)."""
    project = await db.get(Project, project_id)
    if project is None:
        raise PurgeError(f"проект {project_id} не найден")
    pid = project.id
    composition = Composition(
        nodes=await _count(db, Node, Node.project_id == pid),
        threads=await _count(db, Thread, Thread.project_id == pid),
        messages=int(
            await db.scalar(
                select(func.count())
                .select_from(Message)
                .join(Thread, Thread.id == Message.thread_id)
                .where(Thread.project_id == pid)
            )
            or 0
        ),
        notes=await _count(db, ProjectNote, ProjectNote.project_id == pid),
        snapshots=await _count(db, Snapshot, Snapshot.project_id == pid),
        documents=await _count(db, CustomerDocument, CustomerDocument.project_id == pid),
        exports=await _count(db, ExportFile, ExportFile.project_id == pid),
    )
    keys = list(
        await db.scalars(
            select(CustomerDocument.storage_key).where(CustomerDocument.project_id == pid)
        )
    )
    files = [
        p
        for p in await db.scalars(
            select(ExportFile.path).where(
                ExportFile.project_id == pid, ExportFile.path.is_not(None)
            )
        )
        if p
    ]
    return PurgePlan(pid, project.name, composition, keys, files)


def _check_args(ticket: str, approved_by: str) -> tuple[str, str]:
    ticket, approved_by = ticket.strip(), approved_by.strip()
    if not ticket or len(ticket) > TICKET_MAX:
        raise PurgeError("укажите номер заявки (--ticket), до 100 символов")
    if not approved_by or len(approved_by) > LOGIN_MAX:
        raise PurgeError("укажите логин сотрудника ИБ, согласовавшего удаление (--approved-by)")
    return ticket, approved_by


async def record(
    db: AsyncSession,
    target: PurgePlan,
    *,
    ticket: str,
    approved_by: str,
    dry_run: bool,
    os_user: str,
) -> None:
    await audit.write(
        db,
        "project.purged",
        actor="cli",
        os_user=os_user,
        object_type="project",
        object_id=target.project_id,
        project_id=target.project_id,
        details={
            "ticket": ticket,
            "approved_by_login": approved_by,
            "dry_run": dry_run,
            "composition": target.composition.as_dict(),
            "project_name": target.project_name,
        },
    )


async def purge(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    ticket: str,
    approved_by: str,
    dry_run: bool,
    os_user: str,
) -> PurgePlan:
    """Dry-run — только состав и запись в аудит; иначе удалить проект (файлы — :func:`remove_files`
    после commit)."""
    ticket, approved_by = _check_args(ticket, approved_by)
    target = await plan(db, project_id)
    if not dry_run:
        await db.execute(
            delete(Project)
            .where(Project.id == target.project_id)
            .execution_options(synchronize_session=False)
        )
    await record(
        db, target, ticket=ticket, approved_by=approved_by, dry_run=dry_run, os_user=os_user
    )
    return target


def remove_files(target: PurgePlan) -> int:
    """Удалить файлы документов и экспортов проекта с томов; число удалённых файлов."""
    from estimator.documents import storage as documents
    from estimator.exports.engine import storage_dir as exports_dir

    removed = 0
    paths = [documents.path_of(k) for k in target.document_keys]
    paths += [exports_dir() / Path(name).name for name in target.export_files]
    for path in paths:
        for candidate in (path, path.with_name(path.name + ".part")):
            if candidate.exists():
                candidate.unlink()
                removed += 1
    return removed
