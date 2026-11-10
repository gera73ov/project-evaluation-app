"""EXP-003 · фоновые выгрузки (FR-EXP-05, FR-EXP-06, SEC-WEB-07, NFR-REL-06; 14.2
``export_files``; 15.2 ``POST /projects/{id}/exports``, ``GET /exports/{id}``, ``…/download``).

Обработчик проверяет право на вид выгрузки (contracts/exports.yaml → permission) и лимит
30 выгрузок в час, затем :func:`start` пишет строку ``export_files`` (``pending``, срок —
24 часа) и после commit ставит задачу Celery. Задача (:func:`run`) строит файл построителем
вида (:func:`register`), кладёт его в ``exports_dir`` под именем ``<id>.<расширение>``,
переводит строку в ``ready`` и пишет аудит ``export.created`` (вид, снимок, деньги, число
строк). Сбой построителя — ``failed``: ``GET /exports/{id}`` отвечает 409 ``EXPORT_FAILED``.

Состав файла фиксируется при постановке: ``with_money`` — было ли у выгружающего
``money.read`` с TOTP в сессии; построитель денежные колонки без него не пишет (TC-SEC-04).

Файл видит и скачивает только запросивший (``user_id``): чужому — 404, после срока — 410
``EXPORT_EXPIRED``. Скачивание — в аудит ``export.downloaded``. Ночная задача удаляет
просроченные строки и файлы.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.config import get_settings
from estimator.db.enums import ExportStatus
from estimator.db.models.files import ExportFile
from estimator.db.models.users import User
from estimator.db.session import after_commit
from estimator.exports.marks import Mark
from estimator.jobs.schedule import PeriodicTask, register_periodic
from estimator.logging import get_logger
from estimator.security import audit

RETENTION = dt.timedelta(hours=24)  # contracts/exports.yaml common.delivery.retention_hours
BUILD_TASK = "estimator.exports.build"
CLEANUP_TASK = "estimator.exports.cleanup"

log = get_logger(__name__)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class Job:
    """Что нужно задаче, чтобы построить файл; передаётся в Celery как JSON."""

    export_id: uuid.UUID
    kind: str
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    with_money: bool
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "export_id": str(self.export_id),
            "kind": self.kind,
            "user_id": str(self.user_id),
            "project_id": str(self.project_id) if self.project_id else None,
            "snapshot_id": str(self.snapshot_id) if self.snapshot_id else None,
            "with_money": self.with_money,
            "params": dict(self.params),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Job:
        return cls(
            export_id=uuid.UUID(raw["export_id"]),
            kind=raw["kind"],
            user_id=uuid.UUID(raw["user_id"]),
            project_id=uuid.UUID(raw["project_id"]) if raw.get("project_id") else None,
            snapshot_id=uuid.UUID(raw["snapshot_id"]) if raw.get("snapshot_id") else None,
            with_money=bool(raw["with_money"]),
            params=dict(raw.get("params") or {}),
        )


@dataclass(frozen=True)
class Built:
    """Готовый файл: содержимое, имя для пользователя, число строк данных (для аудита)."""

    content: bytes
    file_name: str
    rows: int


Builder = Callable[[AsyncSession, Job, Mark], Awaitable[Built]]
_BUILDERS: dict[str, Builder] = {}


def register(kind: str) -> Callable[[Builder], Builder]:
    """Построитель вида ``kind`` (contracts/exports.yaml → kinds)."""

    def wrap(fn: Builder) -> Builder:
        if kind in _BUILDERS:
            raise ValueError(f"построитель «{kind}» уже зарегистрирован")
        _BUILDERS[kind] = fn
        return fn

    return wrap


def storage_dir() -> Path:
    return Path(get_settings().exports_dir)


async def _enqueue(job: Job) -> None:  # pragma: no cover — нужен брокер Celery
    build_export.apply_async((job.to_json(),))


#: Постановка задачи; тесты подменяют её записью в очередь и запускают :func:`run` сами.
dispatch: Callable[[Job], Awaitable[None]] = _enqueue


async def start(
    db: AsyncSession,
    principal: Principal,
    kind: str,
    *,
    project_id: uuid.UUID | None,
    with_money: bool,
    snapshot_id: uuid.UUID | None = None,
    params: Mapping[str, Any] | None = None,
) -> ExportFile:
    """Записать выгрузку ``pending`` и поставить её построение после commit."""
    if kind not in _BUILDERS:  # pragma: no cover — вид из контракта без построителя
        raise ApiError("VALIDATION_FAILED", detail=f"выгрузка «{kind}» недоступна")
    row = ExportFile(
        id=uuid.uuid4(),
        user_id=principal.user_id,
        project_id=project_id,
        kind=kind,
        snapshot_id=snapshot_id,
        status=ExportStatus.PENDING,
        expires_at=_now() + RETENTION,
    )
    db.add(row)
    await db.flush()
    job = Job(row.id, kind, principal.user_id, project_id, snapshot_id, with_money, params or {})

    async def hook() -> None:
        try:
            await dispatch(job)
        except Exception as exc:  # noqa: BLE001 — сбой постановки не роняет запрос
            log.warning(
                "export_enqueue_failed", export_id=str(job.export_id), error=type(exc).__name__
            )

    after_commit(db, hook)
    return row


async def job_principal(db: AsyncSession, job: Job) -> Principal:
    """Принципал выгружающего для сервисов с побочным эффектом (вопросы → «отправлен»)."""
    from typing import cast

    user = await db.get(User, job.user_id)
    return Principal(
        user_id=job.user_id,
        login=user.login if user else "",
        full_name=user.full_name if user else "",
        roles=frozenset(),
        session_id=f"export:{job.export_id}",
        session=cast(Any, None),
        mfa_passed=True,
    )


async def _mark(db: AsyncSession, user_id: uuid.UUID) -> tuple[Mark, str]:
    user = await db.get(User, user_id)
    zone = (user.timezone if user else None) or get_settings().app_timezone
    name = user.full_name if user else "—"
    return Mark(full_name=name, moment=_now(), timezone=zone), (user.login if user else "")


async def run(db: AsyncSession, job: Job) -> ExportFile | None:
    """Построить файл выгрузки; ``None`` — строки нет или она уже не ``pending``."""
    row = await db.get(ExportFile, job.export_id, with_for_update=True)
    if row is None or row.status is not ExportStatus.PENDING:
        return None
    mark, login = await _mark(db, job.user_id)
    try:
        built = await _BUILDERS[job.kind](db, job, mark)
    except Exception as exc:  # noqa: BLE001 — любой сбой построителя → «не удалась»
        log.error("export_failed", export_id=str(row.id), kind=job.kind, error=type(exc).__name__)
        row.status = ExportStatus.FAILED
        return row
    directory = storage_dir()
    directory.mkdir(parents=True, exist_ok=True)
    ext = Path(built.file_name).suffix or ".bin"
    path = directory / f"{row.id}{ext}"
    await asyncio.to_thread(path.write_bytes, built.content)
    row.path = path.name
    row.file_name = built.file_name
    row.status = ExportStatus.READY
    await audit.write(
        db,
        "export.created",
        user_id=job.user_id,
        login=login,
        object_type="export",
        object_id=row.id,
        project_id=job.project_id,
        details={
            "kind": job.kind,
            "snapshot_id": str(job.snapshot_id) if job.snapshot_id else None,
            "with_money": job.with_money,
            "rows": built.rows,
        },
    )
    return row


def job_out(row: ExportFile) -> dict[str, Any]:
    """``ExportJob`` контракта; ``download_url`` — только у готового файла."""
    ready = row.status is ExportStatus.READY
    return {
        "id": row.id,
        "kind": row.kind,
        "status": "ready" if ready else "pending",
        "file_name": row.file_name if ready else None,
        "download_url": f"/api/v1/exports/{row.id}/download" if ready else None,
        "expires_at": row.expires_at,
    }


async def own(db: AsyncSession, principal: Principal, export_id: uuid.UUID) -> ExportFile:
    """Выгрузка запросившего: чужая — 404, просроченная — 410, неудачная — 409."""
    row = await db.get(ExportFile, export_id)
    if row is None or row.user_id != principal.user_id:
        raise ApiError("NOT_FOUND")
    if row.expires_at <= _now():
        raise ApiError("EXPORT_EXPIRED")
    if row.status is ExportStatus.FAILED:
        raise ApiError("EXPORT_FAILED")
    return row


async def read_file(db: AsyncSession, principal: Principal, row: ExportFile) -> bytes:
    """Содержимое готового файла и аудит ``export.downloaded``; файла нет — 410."""
    if row.status is not ExportStatus.READY or not row.path:
        raise ApiError("NOT_FOUND", detail="Файл ещё готовится")
    path = storage_dir() / Path(row.path).name
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        raise ApiError("EXPORT_EXPIRED") from None
    await audit.write(
        db,
        "export.downloaded",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="export",
        object_id=row.id,
        project_id=row.project_id,
        details={"kind": row.kind},
    )
    return content


async def cleanup(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Удалить просроченные выгрузки и их файлы; число удалённых строк."""
    rows = (
        await db.scalars(select(ExportFile).where(ExportFile.expires_at <= (now or _now())))
    ).all()
    directory = storage_dir()
    for row in rows:
        if row.path:
            (directory / Path(row.path).name).unlink(missing_ok=True)
        await db.delete(row)
    return len(rows)


async def _session_run(work: Callable[[AsyncSession], Awaitable[Any]]) -> Any:  # pragma: no cover
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from estimator.db.session import create_engine

    engine = create_engine(get_settings())  # свой движок: у asyncio.run свой цикл событий
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            return await work(db)
    finally:
        await engine.dispose()


@shared_task(name=BUILD_TASK)
def build_export(raw: dict[str, Any]) -> None:  # pragma: no cover — запуск в worker
    import estimator.exports.kinds  # noqa: F401 — регистрирует построители

    job = Job.from_json(raw)
    asyncio.run(_session_run(lambda db: run(db, job)))


@shared_task(name=CLEANUP_TASK)
def cleanup_exports() -> int:  # pragma: no cover — запуск в worker
    return int(asyncio.run(_session_run(cleanup)))


register_periodic(PeriodicTask("exports_cleanup", CLEANUP_TASK, crontab(minute=15)))
