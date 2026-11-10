"""Источник выгрузок «Часы» и «С деньгами» (EXP-004…006; FR-EXP-03, FR-SNAP-01, BR-ADM-02).

Обе выгрузки строятся из ``payload`` снимка (формат :func:`estimator.services.snapshots.capture`):
для текущего состояния он собирается сейчас, для снимка берётся сохранённый. Так файл из
снимка не меняется после правок дерева и переименований в справочниках. Деньги — из сервиса
денег (текущие или ``money_payload`` снимка), только если выгрузка ``with_money``.

Чего в снимке нет: отметки «Проверено» (в выгрузке из снимка колонка пуста) и категории меток
(берутся из справочника по id метки).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import CommentTag
from estimator.db.models.files import Snapshot
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.domain import calc
from estimator.services import snapshots
from estimator.services.money import snapshot as snapshot_money


class SourceMissing(LookupError):
    """Проекта или снимка нет (удалён между постановкой и построением)."""


@dataclass(frozen=True)
class Source:
    payload: Mapping[str, Any]
    result: calc.ProjectResult
    money: calc.MoneySettings | None
    #: id узла → «✓» (проверено) или «◐» (самопроверка)
    reviewed: Mapping[str, str] = field(default_factory=dict)
    #: id метки → категория (assumption, constraint, risk, tech)
    categories: Mapping[str, str] = field(default_factory=dict)
    snapshot_name: str | None = None
    project_version: int | None = None

    @property
    def project(self) -> Mapping[str, Any]:
        return self.payload["project"]


async def _categories(db: AsyncSession, payload: Mapping[str, Any]) -> dict[str, str]:
    rows = (await db.execute(select(CommentTag.id, CommentTag.category))).all()
    return {str(i): str(c) for i, c in rows}


async def _reviewed(db: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    rows = await db.execute(
        select(Node.id, Node.self_review).where(
            Node.project_id == project_id,
            Node.deleted_at.is_(None),
            Node.reviewed_by.is_not(None),
        )
    )
    return {str(i): "◐" if self_review else "✓" for i, self_review in rows.all()}


async def load(
    db: AsyncSession,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID | None,
    *,
    with_money: bool,
) -> Source:
    project = await db.get(Project, project_id)
    if project is None:
        raise SourceMissing("project")
    if snapshot_id is None:
        payload = await snapshots.capture(db, project)
        raw_money = await snapshot_money.current_payload(db, project.id) if with_money else None
        return Source(
            payload=payload,
            result=snapshots.recalc(payload),
            money=None if raw_money is None else snapshot_money.settings_from_payload(raw_money),
            reviewed=await _reviewed(db, project.id),
            categories=await _categories(db, payload),
            project_version=project.version,
        )
    snap = await db.get(Snapshot, snapshot_id)
    if snap is None or snap.project_id != project_id:
        raise SourceMissing("snapshot")
    raw = None
    if with_money:
        raw = (await snapshot_money.stored_payloads(db, [snap.id])).get(snap.id)
    return Source(
        payload=snap.payload,
        result=snapshots.recalc(snap.payload),
        money=None if raw is None else snapshot_money.settings_from_payload(raw),
        categories=await _categories(db, snap.payload),
        snapshot_name=snap.name,
        project_version=snap.project_version,
    )


def today(moment: dt.datetime, zone: str) -> dt.date:
    from zoneinfo import ZoneInfo

    return moment.astimezone(ZoneInfo(zone)).date()
