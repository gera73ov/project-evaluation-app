"""DB-013 · планы ключевых запросов (SPEC 14.3, NFR-PERF-01, NFR-PERF-02, BR-TREE-06).

Проект «со всем» (как у обходов ИБ) добивается до 5 000 живых узлов — предела BR-TREE-06.
Тест вызывает ключевые экраны через API (дерево, «Мои оценки», статистика, портфель,
уведомления, лента обсуждений, журнал, история узла) и записывает каждый SELECT, который
отправило приложение. Затем строит план каждого запроса с ``enable_seqscan = off``: так
планировщик берёт индекс всегда, когда тот подходит, и «Seq Scan» в плане означает одно —
подходящего индекса нет. Последовательный скан больших таблиц (:data:`LARGE`) — провал.

Отчёт с EXPLAIN ANALYZE: ``PERF_REPORT=путь`` (см. ``REPORT.md`` рядом).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from estimator.db.enums import SystemRole
from tests.integration.core.conftest import World
from tests.security.stocked import stocked

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-PERF-01")]

#: BR-TREE-06: предел живых узлов проекта.
TREE_NODES = 5000

#: Таблицы, которые растут с числом проектов, узлов, правок и пользователей (14.2).
LARGE = frozenset({
    "nodes", "node_history", "change_log", "messages", "message_addressees", "message_history",
    "threads", "notifications", "audit_log", "project_members", "project_notes", "snapshots",
    "export_files", "customer_documents", "branch_status", "user_view_state", "project_rates",
    "project_totals", "project_totals_daily", "support_sessions", "users",
})  # fmt: skip

SEQ_SCAN = re.compile(r"Seq Scan on (\w+)")


@dataclass
class Captured:
    screen: str
    sql: str
    params: Any


@dataclass
class Recorder:
    screen: str = ""
    queries: list[Captured] = field(default_factory=list)
    on: bool = False

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:
        head = statement.lstrip().upper()
        if self.on and not executemany and head.startswith(("SELECT", "WITH")):
            self.queries.append(Captured(self.screen, statement, parameters))


async def _grow_tree(db: AsyncSession, leaf_id: str, project_id: Any) -> int:
    """Размножить лист до :data:`TREE_NODES` живых узлов проекта (копии листа в той же ветке)."""
    live = await db.scalar(
        text("SELECT count(*) FROM nodes WHERE project_id = :p AND deleted_at IS NULL"),
        {"p": project_id},
    )
    extra = TREE_NODES - int(live)
    columns = list(
        await db.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'nodes' AND table_schema = current_schema() "
                "ORDER BY ordinal_position"
            )
        )
    )
    replace = {
        "id": "gen_random_uuid()",
        "title": "'Функция ' || g",
        "position": "'z' || lpad(g::text, 6, '0')",
    }
    select = ", ".join(replace.get(c, c) for c in columns)
    await db.execute(
        text(
            f"INSERT INTO nodes ({', '.join(columns)}) "  # noqa: S608 — имена из каталога
            f"SELECT {select} FROM nodes, generate_series(1, :n) g WHERE id = :leaf"
        ),
        {"n": extra, "leaf": leaf_id},
    )
    return extra


def _write_report(path: Path, timings: dict[str, float], plans: list[str]) -> None:
    rows = "\n".join(f"| {k} | {v * 1000:.0f} |" for k, v in timings.items())
    head = "| Экран | Ответ API, мс |\n|---|---|\n"
    path.write_text(head + rows + "\n\n" + "\n\n".join(plans) + "\n", encoding="utf-8")


async def test_key_queries_use_indexes(
    world: World, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    db = db_session
    st = await stocked(world, db)
    s, ids = st.s, st.ids
    head = await world.actor(SystemRole.PRESALE_HEAD)
    await _grow_tree(db, ids["node"], s.pid)
    await db.execute(text("ANALYZE"))

    recorder = Recorder()
    event.listen(db_engine.sync_engine, "before_cursor_execute", recorder)
    screens = [
        ("Дерево проекта", s.backend_expert, f"/projects/{s.pid}/tree"),
        ("Мои оценки (эксперт)", s.backend_expert, "/projects"),
        ("Мои оценки (модератор)", s.moderator, "/projects"),
        ("Статистика", s.moderator, f"/projects/{s.pid}/stats"),
        ("Портфель", head, "/portfolio/projects"),
        ("Сводка портфеля", head, "/portfolio/summary?from=2026-01-01&to=2026-12-31"),
        ("Уведомления: непрочитанные", s.moderator, "/notifications?unread=true"),
        ("Уведомления: лента", s.moderator, "/notifications"),
        ("Обсуждения проекта", s.moderator, f"/projects/{s.pid}/threads"),
        ("Лента сообщений проекта", s.moderator, f"/projects/{s.pid}/messages"),
        ("Сообщения узла", s.backend_expert, f"/nodes/{ids['node']}/messages"),
        ("Журнал проекта", s.moderator, f"/projects/{s.pid}/journal"),
        ("История узла", s.backend_expert, f"/nodes/{ids['node']}/history"),
    ]
    timings: dict[str, float] = {}
    # Время ответа — без проверки контракта тестовым хуком (на 5 000 узлах она дольше самого
    # ответа); эти ответы сверяют с контрактом функциональные тесты
    hooks = world.api.event_hooks["response"]
    world.api.event_hooks["response"] = []
    try:
        for screen, actor, path in screens:
            recorder.screen, recorder.on = screen, True
            started = time.perf_counter()
            response = await actor.get(path)
            timings[screen] = time.perf_counter() - started
            recorder.on = False
            assert response.status_code == 200, (screen, response.text)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", recorder)
        world.api.event_hooks["response"] = hooks

    tree = (await s.backend_expert.get(f"/projects/{s.pid}/tree")).json()
    assert len(tree["nodes"]) >= TREE_NODES

    conn = await db.connection()
    await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
    failures: list[str] = []
    report: list[str] = []
    for q in recorder.queries:
        plan = "\n".join(row[0] for row in await conn.exec_driver_sql(f"EXPLAIN {q.sql}", q.params))
        scanned = sorted(set(SEQ_SCAN.findall(plan)) & LARGE)
        if scanned:
            failures.append(f"{q.screen}: Seq Scan on {', '.join(scanned)}\n{q.sql}\n{plan}")
        if os.environ.get("PERF_REPORT"):
            await conn.exec_driver_sql("SET LOCAL enable_seqscan = on")
            analyzed = "\n".join(
                row[0]
                for row in await conn.exec_driver_sql(
                    f"EXPLAIN (ANALYZE, BUFFERS OFF, TIMING OFF, SUMMARY ON) {q.sql}", q.params
                )
            )
            await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
            report.append(
                f"### {q.screen}\n\n```sql\n{q.sql.strip()}\n```\n\n```\n{analyzed}\n```\n"
            )
    if os.environ.get("PERF_REPORT"):
        _write_report(Path(os.environ["PERF_REPORT"]), timings, report)
    assert recorder.queries, "приложение не выполнило ни одного SELECT"
    assert not failures, "\n\n".join(failures)
