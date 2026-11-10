"""FE-081 · наполнить проект узлами для замеров рабочего экрана (NFR-PERF-02/03/06).

Запуск из каталога backend, с теми же DATABASE_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/perf/fill.py <project_id> [всего узлов, по умолчанию 5000]

Под каждой веткой дисциплины проекта добавляет группы «узел → 3 подузла → по 3 листа с O/R/P»,
пока в проекте не станет заданное число живых узлов (фазы и ветки дисциплин входят в счёт, как в
BR-TREE-06). Узлы пишутся напрямую в таблицу, без событий WS и истории: сценарий открывает экран
после наполнения. Печатает JSON с числом узлов. Только для dev и тестовых стендов.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import NodeKind
from estimator.db.models.tree import Node
from estimator.db.session import dispose_engine, transaction
from estimator.db.uuid7 import uuid7
from estimator.services.tree.positions import keys_after

GROUP = 1 + 3 + 3 * 3  # узел, три подузла, по три листа


async def fill(project_id: uuid.UUID, total: int) -> dict[str, int]:
    try:
        async with transaction() as db:
            alive = Node.project_id == project_id, Node.deleted_at.is_(None)
            count = (await db.execute(select(func.count()).where(*alive))).scalar_one()
            branches = (
                (await db.execute(select(Node).where(*alive, Node.kind == NodeKind.DISCIPLINE)))
                .scalars()
                .all()
            )
            if not branches:
                raise SystemExit("в проекте нет веток дисциплин")
            groups = max(0, (total - count) // GROUP)
            per_branch = -(-groups // len(branches))
            left = groups
            for branch in branches:
                for g, position in enumerate(keys_after(None, min(per_branch, left))):
                    _group(db, branch, position, f"Модуль {g + 1}")
                    left -= 1
            await db.flush()
            count = (await db.execute(select(func.count()).where(*alive))).scalar_one()
    finally:
        await dispose_engine()
    return {"nodes": count}


def _group(db: AsyncSession, branch: Node, position: str, title: str) -> None:
    def item(parent: Node, pos: str, name: str, hours: tuple[int, int, int] | None = None) -> Node:
        node = Node(
            id=uuid7(),
            project_id=branch.project_id,
            parent_id=parent.id,
            kind=NodeKind.ITEM,
            phase_id=branch.phase_id,
            discipline_id=branch.discipline_id,
            title=name,
            position=pos,
            **(
                {"o": Decimal(hours[0]), "r": Decimal(hours[1]), "p": Decimal(hours[2])}
                if hours
                else {}
            ),
        )
        db.add(node)
        return node

    top = item(branch, position, title)
    for s, sub_pos in enumerate(keys_after(None, 3)):
        sub = item(top, sub_pos, f"{title}.{s + 1}")
        for leaf, leaf_pos in enumerate(keys_after(None, 3)):
            base = 2 + (s * 3 + leaf) % 7
            item(sub, leaf_pos, f"Задача {title}.{s + 1}.{leaf + 1}", (base, base * 2, base * 4))


if __name__ == "__main__":
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    print(json.dumps(asyncio.run(fill(uuid.UUID(sys.argv[1]), target))))  # вывод читает сценарий
