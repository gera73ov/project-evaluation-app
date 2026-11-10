"""Служебный реестр проектов суперадминистратора (ADM-005; SPEC 3.2, 11.2 №1, CL-09;
contracts/openapi.yaml ``GET /system/projects``).

Название, модераторы, статус, даты — без денег, дерева и обсуждений. Открыть проект
суперадминистратор не может: проектных прав у него нет (permissions.yaml), чтение проекта и
дерева — 404 (SEC-AUTHZ-05). Строки — те же, что в реестре администратора
(:mod:`estimator.admin.registry`), без фильтров.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import registry


async def page(
    db: AsyncSession, *, after: dict[str, Any] | None, limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    return await registry.page(db, registry.Filter(), after=after, limit=limit)
