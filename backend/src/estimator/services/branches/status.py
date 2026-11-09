"""Статус ветки при правке дерева (SPEC 4.3, BR-BR-02; часть CORE-015, остальное — CORE-018).

* первая правка ветки: «не начато» → «черновик»;
* правка O/R/P, ×N, добавление узла: «готово» → «черновик»;
* переименование, смена типа, комментарий «готово» не сбрасывают.

Смена статуса — событие ``branch.status`` со своей версией проекта. Уведомление модератору
«Ветка вернулась в черновик» и снятие «Проверено» подключит CORE-018.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.enums import BranchStatusValue
from estimator.db.models.projects import BranchStatus
from estimator.services.common import emit, user_ref


async def touch(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    phase_id: uuid.UUID,
    discipline_id: uuid.UUID,
    *,
    resets_done: bool,
) -> dict[str, Any] | None:
    """Пересчитать статус ветки после правки; изменение (``BranchStatusChange``) или ``None``."""
    row = await db.get(BranchStatus, (project_id, phase_id, discipline_id))
    if row is None:
        return None
    was = row.status
    if was is BranchStatusValue.NOT_STARTED or (resets_done and was is BranchStatusValue.DONE):
        new = BranchStatusValue.DRAFT
    else:
        return None
    row.status = new
    row.changed_by = principal.user_id
    row.changed_at = dt.datetime.now(dt.UTC)
    change = {
        "phase_id": str(phase_id),
        "discipline_id": str(discipline_id),
        "status": new.value,
        "was": was.value,
    }
    await emit(
        db,
        project_id,
        "branch.status",
        change | {"author": user_ref(principal.user_id, principal.full_name)},
    )
    return change
