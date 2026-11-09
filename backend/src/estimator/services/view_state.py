"""CORE-027 · состояние вида пользователя в проекте (SPEC FR-TREE-14, 14.2 ``user_view_state``;
15.2 ``GET/PUT /me/view-state/{project_id}``).

Раскрытие, фильтры и ширины колонок хранятся на сервере для пары «пользователь × проект»,
поэтому вид, сохранённый в одном браузере, открывается в другом. Содержимое сервер не
разбирает (это дело клиента), ограничен только размер: ≤ 64 КБ в JSON (схема ``ViewState``).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.models.tree import UserViewState

MAX_BYTES = 64 * 1024


def encoded_size(state: Mapping[str, Any]) -> int:
    return len(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


async def get_state(db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    row = await db.get(UserViewState, (user_id, project_id))
    return dict(row.state) if row is not None else {}


async def put_state(
    db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, state: Mapping[str, Any]
) -> dict[str, Any]:
    if encoded_size(state) > MAX_BYTES:
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            detail="Состояние вида больше 64 КБ",
            limit_bytes=MAX_BYTES,
        )
    stmt = insert(UserViewState).values(
        user_id=user_id,
        project_id=project_id,
        state=dict(state),
        updated_at=dt.datetime.now(dt.UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserViewState.user_id, UserViewState.project_id],
        set_={"state": stmt.excluded.state, "updated_at": stmt.excluded.updated_at},
    )
    await db.execute(stmt)
    row = await db.get(UserViewState, (user_id, project_id), populate_existing=True)
    return dict(row.state) if row is not None else dict(state)
