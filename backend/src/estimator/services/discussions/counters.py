"""Счётчики обсуждений в дереве (CORE-040; FR-DISC-04, FR-TREE-11).

У строки узла: ``messages_count`` — все записи ленты узла, включая серые события (N в «Показать
всё (N)»); ``open_questions`` — открытые вопросы узла (оранжевый значок); ``questions_to_me`` —
открытые вопросы узла, где зритель среди адресатов (красная точка). У ветки — открытые вопросы
во всех её узлах. У проекта (шапка «Открыто», CORE-045, CR-013) — открытые вопросы узлов
и проекта и из них «мне».
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ThreadStatus
from estimator.db.models.discussions import Message, Thread
from estimator.db.models.tree import Node
from estimator.services.discussions.addressees import team
from estimator.services.discussions.feed import addressed


@dataclass(frozen=True)
class Counters:
    messages: Counter[uuid.UUID] = field(default_factory=Counter)
    open: Counter[uuid.UUID] = field(default_factory=Counter)
    to_me: Counter[uuid.UUID] = field(default_factory=Counter)
    branches: Counter[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=Counter)
    project_open: int = 0
    project_to_me: int = 0

    def node(self, node_id: uuid.UUID) -> dict[str, int]:
        return {
            "messages_count": self.messages[node_id],
            "open_questions": self.open[node_id],
            "questions_to_me": self.to_me[node_id],
        }


async def tree_counters(
    db: AsyncSession, project_id: uuid.UUID, viewer: uuid.UUID | None
) -> Counters:
    """Счётчики всех узлов проекта для зрителя ``viewer`` (``None`` — без «вопросов мне»)."""
    messages = await db.execute(
        select(Message.node_id, func.count())
        .where(Message.project_id == project_id, Message.node_id.is_not(None))
        .group_by(Message.node_id)
    )
    is_open = (
        Thread.project_id == project_id,
        Thread.status == ThreadStatus.OPEN,
        Thread.node_id.is_not(None),
    )
    opened = await db.execute(
        select(Thread.node_id, func.count()).where(*is_open).group_by(Thread.node_id)
    )
    branches = await db.execute(
        select(Node.phase_id, Node.discipline_id, func.count())
        .select_from(Thread)
        .join(Node, Node.id == Thread.node_id)
        .where(*is_open, Node.discipline_id.is_not(None))
        .group_by(Node.phase_id, Node.discipline_id)
    )
    in_project = (Thread.project_id == project_id, Thread.status == ThreadStatus.OPEN)
    project_open = int(await db.scalar(select(func.count()).where(*in_project)) or 0)
    to_me: Counter[uuid.UUID] = Counter()
    project_to_me = 0
    if viewer is not None:
        tokens = (await team(db, project_id)).tokens(viewer)
        rows = await db.execute(
            select(Thread.node_id, func.count())
            .where(*in_project, addressed(tokens))
            .group_by(Thread.node_id)
        )
        for n, c in rows.all():
            project_to_me += int(c)
            if n is not None:
                to_me[n] = int(c)
    return Counters(
        messages=Counter({n: int(c) for n, c in messages.all()}),
        open=Counter({n: int(c) for n, c in opened.all()}),
        to_me=to_me,
        branches=Counter({(p, d): int(c) for p, d, c in branches.all()}),
        project_open=project_open,
        project_to_me=project_to_me,
    )
