"""Закрытие и переоткрытие обычного вопроса (CORE-041; FR-DISC-05, 4.4 «Обычное обсуждение»).

Кто может, проверяет право ``thread.resolve``: модератор — любой вопрос, эксперт и пресейл —
вопрос, где они автор или адресат (``author_or_addressee``). Повторное закрытие и переоткрытие
открытого — 409 ``INVALID_TRANSITION``. «Добавить вывод в комментарий листа» добавляет строку в
``comment_lines`` узла вопроса обычной правкой узла (история, версия, «Проверено», FR-TREE-34) и
требует права ``comment.write`` на узле. Вопросы заказчику закрывает и переоткрывает CORE-044.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ThreadStatus
from estimator.db.models.discussions import Thread
from estimator.db.models.tree import Node
from estimator.services.common import emit
from estimator.services.discussions import feed
from estimator.services.discussions.addressees import invalid


async def _publish(db: AsyncSession, principal: Principal, thread: Thread, event: str) -> None:
    await db.flush()
    await emit(
        db,
        thread.project_id,
        event,
        {
            "thread": feed.ws_thread(thread, await feed.thread_addressees(db, thread.id)),
            "author": await feed.author_ref(db, principal.user_id),
        },
    )


def conclusion_lines(node: Node, text: str, tag_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """Строки комментария узла с выводом в конце (R-03: проверки — в правке узла)."""
    body = text.strip()
    if not body:
        raise invalid("conclusion/text", "вывод не может быть пустым")
    lines = [
        {"tag_id": uuid.UUID(str(line["tag_id"])) if line.get("tag_id") else None,
         "text": line["text"]}
        for line in (node.comment_lines or [])
    ]  # fmt: skip
    return [*lines, {"tag_id": tag_id, "text": body}]


async def resolve(db: AsyncSession, principal: Principal, thread: Thread) -> None:
    if thread.status is ThreadStatus.RESOLVED:
        raise ApiError("INVALID_TRANSITION", detail="Вопрос уже решён")
    thread.status = ThreadStatus.RESOLVED
    thread.resolved_by = principal.user_id
    thread.resolved_at = dt.datetime.now(dt.UTC)
    thread.updated_by = principal.user_id
    await _publish(db, principal, thread, "thread.resolved")


async def reopen(db: AsyncSession, principal: Principal, thread: Thread) -> None:
    if thread.status is ThreadStatus.OPEN:
        raise ApiError("INVALID_TRANSITION", detail="Вопрос уже открыт")
    thread.status = ThreadStatus.OPEN
    thread.resolved_by = None
    thread.resolved_at = None
    thread.updated_by = principal.user_id
    await _publish(db, principal, thread, "thread.reopened")
