"""CORE-018: статус ветки — ручные переходы диаграммы 4.3, «готово» только без пустых и неверных
листьев (BR-BR-01), «не нужно» только для пустой ветки, сброс «готово» по таблице BR-BR-02 и
уведомление «Ветка вернулась в черновик» (FR-NOTIF-01). Строки таблицы для удаления, переноса,
разбиения и сворачивания добавят CORE-016 и CORE-017."""

from __future__ import annotations

import itertools
import uuid
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import BranchStatus
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.branches.status import MANUAL
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.test_nodes_api import Setup, _create, _patch, _setup

pytestmark = [pytest.mark.integration, pytest.mark.spec("4.3"), pytest.mark.spec("BR-BR-01")]

S = BranchStatusValue


async def _put(actor: Actor, s: Setup, phase: Any, discipline: Any, status: str) -> Any:
    return await actor.put(
        f"/projects/{s.pid}/branches/{phase}/{discipline}/status", json={"status": status}
    )


async def _force(db: AsyncSession, s: Setup, phase: uuid.UUID, status: S) -> None:
    await db.execute(
        update(BranchStatus)
        .where(
            BranchStatus.project_id == s.pid,
            BranchStatus.phase_id == phase,
            BranchStatus.discipline_id == s.backend,
        )
        .values(status=status)
    )


async def _status(db: AsyncSession, s: Setup, phase: uuid.UUID) -> S:
    row = await db.get(BranchStatus, (s.pid, phase, s.backend), populate_existing=True)
    return row.status


@pytest.mark.parametrize(("was", "to"), list(itertools.product(S, S)))
async def test_manual_matrix(world: World, db_session: AsyncSession, was: S, to: S) -> None:
    """Каждая пара статусов на пустой ветке: стрелка диаграммы — 200, иначе 409."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _force(db_session, s, branch.phase_id, was)
    response = await _put(s.moderator, s, branch.phase_id, s.backend, to.value)
    if (was, to) in MANUAL:
        assert response.status_code == 200, response.text
        assert response.json() == {
            "phase_id": str(branch.phase_id),
            "discipline_id": str(s.backend),
            "status": to.value,
            "was": was.value,
        }
        assert await _status(db_session, s, branch.phase_id) is to
    else:
        assert response.status_code == 409, response.text
        body = response.json()
        assert (body["code"], body["from"], body["to"]) == (
            "INVALID_TRANSITION",
            was.value,
            to.value,
        )


async def test_done_requires_ready_leaves(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    empty = (await _create(s.backend_expert, s.pid, branch.id, title="Пусто")).json()["node"]
    wrong = (
        await _create(s.backend_expert, s.pid, branch.id, title="Ошибка", o="10", r="5", p="20")
    ).json()["node"]
    await _create(s.backend_expert, s.pid, branch.id, title="Ноль", o="0", r="0", p="0")
    blocked = await _put(s.backend_expert, s, branch.phase_id, s.backend, "done")
    assert (blocked.status_code, blocked.json()["code"]) == (409, "BRANCH_NOT_READY")
    assert set(blocked.json()["node_ids"]) == {empty["id"], wrong["id"]}

    await _patch(s.backend_expert, empty["id"], 1, o="1", r="2", p="3")
    await _patch(s.backend_expert, wrong["id"], 1, o="4")
    done = await _put(s.backend_expert, s, branch.phase_id, s.backend, "done")
    assert done.status_code == 200, done.text
    assert done.json()["was"] == "draft"
    await deliver_events(db_session)
    [event] = [e for e in events.on(f"project:{s.pid}") if e["event"] == "branch.status"][-1:]
    assert event["data"]["status"] == "done"
    assert event["data"]["author"]["id"] == str(s.backend_expert.id)

    # эксперт чужой дисциплины и «не нужно» от эксперта — 403
    frontend = await s.branch(db_session, s.frontend)
    await _create(s.frontend_expert, s.pid, frontend.id, title="Экран", o="1", r="2", p="3")
    foreign = await _put(s.backend_expert, s, frontend.phase_id, s.frontend, "done")
    assert foreign.status_code == 403
    other = await s.branch(db_session, s.backend)
    phases = (
        await db_session.scalars(
            select(BranchStatus.phase_id).where(
                BranchStatus.project_id == s.pid,
                BranchStatus.discipline_id == s.backend,
                BranchStatus.phase_id != other.phase_id,
            )
        )
    ).all()
    not_needed = await _put(s.backend_expert, s, phases[0], s.backend, "not_needed")
    assert not_needed.status_code == 403
    missing = await _put(s.moderator, s, uuid.uuid4(), s.backend, "done")
    assert missing.status_code == 404


async def test_not_needed_only_empty(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _create(s.backend_expert, s.pid, branch.id, title="Лист")
    busy = await _put(s.moderator, s, branch.phase_id, s.backend, "not_needed")
    assert (busy.status_code, busy.json()["code"]) == (409, "BRANCH_NOT_EMPTY")


@pytest.mark.spec("BR-BR-02")
@pytest.mark.tc("TC-BR-01")
@pytest.mark.spec("FR-NOTIF-01")
async def test_done_reset_table(world: World, db_session: AsyncSession) -> None:
    """TC-BR-01, строки для правки и добавления: что сбрасывает «готово», а что нет."""
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    leaf = (
        await _create(s.backend_expert, s.pid, branch.id, title="Вход", o="1", r="2", p="3")
    ).json()["node"]
    tag = None
    version = 1

    async def edit(**changes: Any) -> Any:
        nonlocal version
        response = await _patch(s.moderator, leaf["id"], version, **changes)
        assert response.status_code == 200, response.text
        version = response.json()["node"]["version"]
        return response.json()

    rows: list[tuple[str, dict[str, Any] | None, bool]] = [
        ("rename", {"title": "Вход 2"}, False),
        ("comment", {"comment_lines": [{"tag_id": tag, "text": "SSO"}]}, False),
        ("o", {"o": "1.5"}, True),
        ("r", {"r": "2.5"}, True),
        ("p", {"p": "3.5"}, True),
        ("multiplier", {"multiplier": 2}, True),
        ("add", None, True),
    ]
    for name, changes, resets in rows:
        await _force(db_session, s, branch.phase_id, S.DONE)
        if changes is None:
            result = (await _create(s.moderator, s.pid, branch.id, title="Новый")).json()
        else:
            result = await edit(**changes)
        expected = S.DRAFT if resets else S.DONE
        assert await _status(db_session, s, branch.phase_id) is expected, name
        assert (result["branch_status"] is not None) is resets, name

    notes = (
        await db_session.scalars(
            select(Notification).where(Notification.kind == "branch_back_to_draft")
        )
    ).all()
    # каждый сброс — эксперту Бэкенда; модератор — автор правки, ему не приходит
    assert {n.user_id for n in notes} == {s.backend_expert.id}
    assert len(notes) == 5
    assert notes[0].payload == {
        "project_id": str(s.pid),
        "phase_id": str(branch.phase_id),
        "discipline_id": str(s.backend),
        "actor_id": str(s.moderator.id),
    }
