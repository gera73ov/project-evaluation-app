"""CORE-021: история узла и «Вернуть это значение» (FR-TREE-25); CORE-022: правка модератором
чужой ветки — уведомление ``moderator_change`` экспертам (FR-TREE-34); строки TC-BR-01 для удаления
и восстановления (BR-BR-02)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.discussions import Notification
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import _create, _patch, _setup
from tests.integration.core.test_review_api import _review, _with_reviewer
from tests.integration.core.test_structure_api import _force_done, _leaf, _node

pytestmark = [pytest.mark.integration]


@pytest.mark.spec("FR-TREE-25")
async def test_history_and_revert(world: World, db_session: AsyncSession) -> None:
    s, reviewer = await _with_reviewer(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Вход", o="30", r="40", p="60")
    await _patch(s.backend_expert, leaf["id"], 1, r="50")
    await _patch(s.moderator, leaf["id"], 2, p="80")
    await _review(reviewer, leaf["id"])

    first = await s.frontend_expert.get(f"/nodes/{leaf['id']}/history", params={"limit": 2})
    assert first.status_code == 200, first.text
    page = first.json()
    assert [e["action"] for e in page["items"]] == ["review", "update"]
    assert page["items"][1]["changes"] == {"p": ["60", "80"]}
    assert page["items"][1]["user"]["id"] == str(s.moderator.id)
    rest = await s.frontend_expert.get(
        f"/nodes/{leaf['id']}/history", params={"cursor": page["next_cursor"]}
    )
    assert [e["action"] for e in rest.json()["items"]] == ["update", "create"]
    assert rest.json()["next_cursor"] is None
    bad = await s.frontend_expert.get(f"/nodes/{leaf['id']}/history", params={"cursor": "x"})
    assert (bad.status_code, bad.json()["code"]) == (400, "CURSOR_INVALID")

    # «Вернуть 30–40–60» — обычная правка: новая запись истории, «Проверено» снимается
    version = (await _node(db_session, leaf["id"])).version
    revert = await _patch(s.backend_expert, leaf["id"], version, r="40", p="60")
    assert revert.status_code == 200, revert.text
    assert revert.json()["node"]["reviewed_by"] is None
    latest = (await s.backend_expert.get(f"/nodes/{leaf['id']}/history")).json()["items"][0]
    assert latest["changes"] == {"r": ["50", "40"], "p": ["80", "60"], "review": [True, False]}


async def _notes(db: AsyncSession) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification)
                .where(Notification.kind == "moderator_change")
                .order_by(Notification.created_at, Notification.id)
            )
        ).all()
    )


@pytest.mark.spec("FR-TREE-34")
async def test_moderator_change_notifies_experts(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Вход", o="1", r="2", p="3")
    await _patch(s.backend_expert, leaf["id"], 1, o="1.5")  # правка эксперта — без уведомления
    assert await _notes(db_session) == []

    await _patch(s.moderator, leaf["id"], 2, o="2", title="Вход по SSO")
    added = (await _create(s.moderator, s.pid, branch.id, title="Новое")).json()["node"]
    await s.moderator.delete(f"/nodes/{added['id']}")
    notes = await _notes(db_session)
    assert {n.user_id for n in notes} == {s.backend_expert.id}  # фронтенду и автору — нет
    assert [n.payload["fields"] for n in notes] == [["title", "o"], ["structure"], ["structure"]]
    assert notes[0].payload == {
        "project_id": str(s.pid),
        "node_id": leaf["id"],
        "actor_id": str(s.moderator.id),
        "fields": ["title", "o"],
    }


@pytest.mark.spec("BR-BR-02")
@pytest.mark.spec("TC-BR-01")
async def test_done_reset_delete_and_restore(world: World, db_session: AsyncSession) -> None:
    """TC-BR-01, строки «удаление» и «восстановление из корзины»: «готово» → «черновик»."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Остаётся", o="1", r="2", p="3")
    gone = await _leaf(s.backend_expert, s, branch.id, "Уходит", o="1", r="2", p="3")
    await _force_done(db_session, s, branch.phase_id, s.backend)
    deleted = await s.backend_expert.delete(f"/nodes/{gone['id']}")
    assert [c["status"] for c in deleted.json()["branch_statuses"]] == ["draft"]
    await _force_done(db_session, s, branch.phase_id, s.backend)
    restored = await s.backend_expert.post(f"/trash/{deleted.json()['batch_id']}/restore", json={})
    assert restored.status_code == 200, restored.text
    assert [c["status"] for c in restored.json()["branch_statuses"]] == ["draft"]
