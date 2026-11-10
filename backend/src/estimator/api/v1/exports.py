"""Выгрузки (EXP-003…006; contracts/openapi.yaml ``createExport``, ``getExport``,
``downloadExport``).

``POST /projects/{id}/exports`` ставит «Часы» (``export.hours``) или «С деньгами»
(``export.money`` с TOTP) из текущего состояния или снимка проекта; лимит — 30 выгрузок в час
на пользователя (SEC-WEB-07). Статус и файл видит только запросивший
(:func:`estimator.exports.engine.own`). Построение — :mod:`estimator.exports.engine`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.context import Principal
from estimator.auth.mfa_policy import ActivePrincipal, RedisDep
from estimator.db.models.discussions import Thread
from estimator.db.models.files import ExportFile, Snapshot
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.exports import engine
from estimator.exports import kinds as _kinds  # noqa: F401 — регистрирует построители
from estimator.security.authz.deps import AuthorizerDep, register_resolver, target_from_path
from estimator.security.authz.engine import Target
from estimator.security.ratelimit.limiter import LIMITS, RateLimiter
from estimator.services.discussions.addressees import invalid

router = ApiRouter(tags=["Статистика, снимки, экспорт"])


async def export_target(db: AsyncSession, export_id: uuid.UUID) -> Target | None:
    """Объект ``/exports/{id}``: проект выгрузки (или системный объект для портфеля и аудита)."""
    row = (
        await db.execute(
            select(ExportFile.project_id, Project.status)
            .outerjoin(Project, Project.id == ExportFile.project_id)
            .where(ExportFile.id == export_id)
        )
    ).first()
    if row is None:
        return None
    project_id, status = row
    if project_id is None:
        return Target()
    return Target(project_id=project_id, project_status=str(status))


register_resolver("/exports/{id}", export_target)


async def limit_exports(redis: RedisDep, principal: Principal) -> None:
    """30 выгрузок в час на пользователя (SEC-WEB-07) — для всех видов."""
    await RateLimiter(redis).check(LIMITS["exports"], str(principal.user_id))


@router.post(
    "/projects/{id}/exports",
    permission=["export.hours", "export.money"],
    status_code=202,
    response_model=s.ExportJob,
)
async def create_export(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ExportCreate,
    request: Request,
    principal: ActivePrincipal,
    authz: AuthorizerDep,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    target = await target_from_path(request, db)
    with_money = body.kind == "money_xlsx"
    await authz.check("export.money" if with_money else "export.hours", target)
    if body.snapshot_id is not None:
        snap = await db.get(Snapshot, body.snapshot_id)
        if snap is None or snap.project_id != id:
            raise invalid("snapshot_id", "снимка нет в проекте")
    await limit_exports(redis, principal)
    row = await engine.start(
        db, principal, body.kind, project_id=id, snapshot_id=body.snapshot_id, with_money=with_money
    )
    return engine.job_out(row)


@router.post(
    "/projects/{id}/customer-questions/export",
    permission="cq.manage",
    status_code=202,
    response_model=s.ExportJob,
    tags=["Обсуждения"],
)
async def export_customer_questions(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.CqExportRequest,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """Выбранные вопросы в Excel или Word; выгруженные «новые» → «отправлен» (EXP-007)."""
    ids = list(dict.fromkeys(body.thread_ids))
    found = set(
        (
            await db.scalars(
                select(Thread.id).where(
                    Thread.project_id == id, Thread.id.in_(ids), Thread.is_customer
                )
            )
        ).all()
    )
    if len(found) != len(ids):
        raise invalid("thread_ids", "это не вопросы заказчику этого проекта")
    await limit_exports(redis, principal)
    row = await engine.start(
        db,
        principal,
        f"cq_{body.format}",
        project_id=id,
        with_money=False,
        params={"thread_ids": [str(i) for i in ids]},
    )
    return engine.job_out(row)


@router.post(
    "/snapshots/{id}/diff/export",
    permission="export.hours",
    status_code=202,
    response_model=s.ExportJob,
)
async def export_diff(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.DiffExportRequest,
    request: Request,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """Сравнение снимка с текущим состоянием или другим снимком в Excel (EXP-008)."""
    base = await db.get(Snapshot, id)
    if base is None:  # pragma: no cover — gate уже ответил 404
        raise ApiError("NOT_FOUND")
    other = body.with_
    if other != "current":
        try:
            found = await db.get(Snapshot, uuid.UUID(other))
        except ValueError:
            found = None
        if found is None or found.project_id != base.project_id:
            raise invalid("with", "нужен current или снимок этого проекта")
    access = getattr(request.state, "access", None)
    await limit_exports(redis, principal)
    row = await engine.start(
        db,
        principal,
        "snapshot_diff_xlsx",
        project_id=base.project_id,
        snapshot_id=base.id,
        with_money=bool(access and access.money),
        params={"with": other},
    )
    return engine.job_out(row)


StatsTab = Literal[
    "readiness",
    "totals",
    "ratios",
    "volumes",
    "candidates",
    "tags",
    "discussions",
    "customer_questions",
    "reviewed",
    "snapshots",
    "dynamics",
]


@router.get(
    "/projects/{id}/stats/{tab}/export",
    permission="export.hours",
    status_code=202,
    response_model=s.ExportJob,
)
async def export_stats_tab(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    tab: StatsTab,
    format: Annotated[Literal["xlsx"], Query()],  # noqa: A002 — имя параметра из контракта
    request: Request,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """Таблицы вкладки статистики в Excel (EXP-009); деньги — только с ``money.read``."""
    access = getattr(request.state, "access", None)
    await limit_exports(redis, principal)
    row = await engine.start(
        db,
        principal,
        "stats_tab_xlsx",
        project_id=id,
        with_money=bool(access and access.money),
        params={"tab": tab},
    )
    return engine.job_out(row)


@router.get(
    "/projects/{id}/assumptions/export",
    permission="export.money",
    status_code=202,
    response_model=s.ExportJob,
)
async def export_assumptions(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """Word «Допущения и риски» — черновик раздела КП (EXP-009)."""
    await limit_exports(redis, principal)
    row = await engine.start(db, principal, "assumptions_docx", project_id=id, with_money=False)
    return engine.job_out(row)


@router.post(
    "/portfolio/export",
    permission="portfolio.export",
    status_code=202,
    response_model=s.ExportJob,
    tags=["Руководитель пресейла"],
)
async def export_portfolio(
    body: s.PortfolioExport,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    """Реестр и сводка портфеля за период в Excel (EXP-010)."""
    if body.from_ > body.to:
        raise invalid("from", "начало периода позже конца")
    await limit_exports(redis, principal)
    row = await engine.start(
        db,
        principal,
        "portfolio_xlsx",
        project_id=None,
        with_money=True,
        params={"from": body.from_.isoformat(), "to": body.to.isoformat()},
    )
    return engine.job_out(row)


@router.get(
    "/exports/{id}",
    permission=["export.hours", "export.money", "cq.manage", "portfolio.export", "audit.export"],
    step_up=False,  # step-up был при постановке выгрузки аудита; файл отдаётся её автору
    response_model=s.ExportJob,
)
async def get_export(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    return engine.job_out(await engine.own(db, principal, id))


@router.get(
    "/exports/{id}/download",
    permission=["export.hours", "export.money", "cq.manage", "portfolio.export", "audit.export"],
    step_up=False,  # step-up был при постановке выгрузки аудита; файл отдаётся её автору
    response_class=Response,
)
async def download_export(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> Response:
    row = await engine.own(db, principal, id)
    content = await engine.read_file(db, principal, row)
    name = row.file_name or f"{row.id}"
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    disposition = f"attachment; filename=\"export{ext}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content,
        media_type="application/octet-stream",  # контракт; вид файла — по имени
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
