"""Кэш расчёта для ответа правки (NFR-PERF-03, 15.3; QA-019): ответ PATCH и POST узла совпадает
с деревом при любом пути — построили заново, версия совпала, догнали по ``change_log`` после
правок другого экземпляра, — а события, которые меняют структуру, заставляют строить заново."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.services.tree import calc_cache
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.test_nodes_api import _create, _patch, _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("NFR-PERF-03"), pytest.mark.spec("15.3")]

FIGURES = (
    "e", "sigma", "p80", "p90", "sum_o", "sum_r", "sum_p", "leaf_state", "unaccounted_leaves",
    "is_large", "is_repeating", "messages_count", "open_questions", "questions_to_me",
)  # fmt: skip


def _count(result: str) -> float:
    return calc_cache._RESULTS.labels(result)._value.get()


class Paths:
    """Сколько раз сработал каждый путь кэша с момента создания."""

    def __init__(self) -> None:
        self.start = {r: _count(r) for r in ("hit", "delta", "rebuild")}

    def taken(self) -> dict[str, int]:
        return {r: int(_count(r) - v) for r, v in self.start.items() if _count(r) - v}


async def _same_as_tree(actor: Actor, pid: uuid.UUID, response: Any) -> dict[str, Any]:
    """Ответ правки сверяется с деревом; затем «commit» — состояние запоминается."""
    assert response.status_code in (200, 201), response.text
    body = response.json()
    tree = (await actor.get(f"/projects/{pid}/tree")).json()
    by_id = {n["id"]: n for n in tree["nodes"]}
    node = body["node"]
    assert {k: node[k] for k in FIGURES} == {k: by_id[node["id"]][k] for k in FIGURES}
    want = []
    parent = by_id[node["id"]]["parent_id"]
    while parent is not None:
        want.append({"id": parent, "e": by_id[parent]["e"], "sigma": by_id[parent]["sigma"]})
        parent = by_id[parent]["parent_id"]
    assert body["ancestors"] == want
    assert body["totals"] == tree["totals"]["total"]
    assert body["project_version"] == tree["project_version"]
    await deliver_events(actor.world.db)
    return node


async def test_mutation_response_matches_tree_on_every_path(
    world: World, db_session: AsyncSession
) -> None:
    s = await _setup(world, db_session)
    expert = s.backend_expert
    branch = await s.branch(db_session, s.backend)
    calc_cache.clear()

    paths = Paths()
    a = await _same_as_tree(expert, s.pid, await _create(expert, s.pid, branch.id, title="А",
                                                         o="8", r="12", p="20"))  # fmt: skip
    assert paths.taken() == {"rebuild": 1}

    paths = Paths()
    group = await _same_as_tree(expert, s.pid, await _create(expert, s.pid, branch.id, title="Г"))
    b = await _same_as_tree(expert, s.pid, await _create(expert, s.pid, group["id"], title="Б",
                                                         o="1", r="2", p="40"))  # fmt: skip
    a = await _same_as_tree(expert, s.pid, await _patch(expert, a["id"], a["version"], o="10"))
    assert paths.taken() == {"delta": 3}  # своя же предыдущая правка — одно событие в хвосте

    # «другой экземпляр»: этот знает версию до правок Б и вопроса; догоняет по change_log
    behind = calc_cache._snapshots[s.pid]
    b = await _same_as_tree(expert, s.pid, await _patch(expert, b["id"], b["version"], p="80",
                                                        multiplier=3))  # fmt: skip
    asked = await expert.post(f"/nodes/{b['id']}/messages", json={
        "body": "Нужен SSO?", "needs_answer": True,
        "addressees": [{"target_type": "user", "target_id": str(s.moderator.id)}],
    })  # fmt: skip
    assert asked.status_code == 201, asked.text
    calc_cache._snapshots[s.pid] = behind
    paths = Paths()
    a = await _same_as_tree(expert, s.pid, await _patch(expert, a["id"], a["version"], r="15"))
    assert paths.taken() == {"delta": 1}

    # удаление в хвосте — строить заново
    gone = await expert.delete(f"/nodes/{b['id']}")
    assert gone.status_code == 200, gone.text
    paths = Paths()
    a = await _same_as_tree(expert, s.pid, await _patch(expert, a["id"], a["version"], p="30"))
    assert paths.taken() == {"rebuild": 1}

    # версия без события (изменение мимо change_log) — строить заново
    await db_session.execute(
        text("UPDATE projects SET version = version + 1 WHERE id = :p"), {"p": s.pid}
    )
    paths = Paths()
    a = await _same_as_tree(expert, s.pid, await _patch(expert, a["id"], a["version"], o="9"))
    assert paths.taken() == {"rebuild": 1}

    # статус ветки поменялся мимо кэша — отпечаток параметров другой, строить заново
    snapshot = calc_cache._snapshots[s.pid]
    calc_cache._snapshots[s.pid] = calc_cache.Snapshot(
        snapshot.version, ("другой",), snapshot.state, snapshot.at
    )
    paths = Paths()
    await _same_as_tree(expert, s.pid, await _patch(expert, a["id"], a["version"], o="8"))
    assert paths.taken() == {"rebuild": 1}


async def test_unchanged_patch_hits_cache(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    expert = s.backend_expert
    branch = await s.branch(db_session, s.backend)
    a = await _same_as_tree(expert, s.pid, await _create(expert, s.pid, branch.id, title="А",
                                                         o="8", r="12", p="20"))  # fmt: skip
    paths = Paths()
    same = await _patch(expert, a["id"], a["version"], o="8")  # то же значение: версия не растёт
    await _same_as_tree(expert, s.pid, same)
    assert paths.taken() == {"hit": 1}


def test_remember_keeps_newest_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calc_cache.clear()
    state: Any = object()
    first, second = uuid.uuid4(), uuid.uuid4()
    calc_cache.remember(first, calc_cache.Snapshot(5, (), state, 0.0))
    calc_cache.remember(first, calc_cache.Snapshot(4, (), state, 0.0))  # опоздавший commit
    assert calc_cache._snapshots[first].version == 5
    monkeypatch.setattr(calc_cache, "MAX_PROJECTS", 1)
    calc_cache.remember(second, calc_cache.Snapshot(1, (), state, 0.0))
    assert list(calc_cache._snapshots) == [second]
    calc_cache.clear()
