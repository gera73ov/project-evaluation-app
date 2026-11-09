"""CORE-027: состояние вида на сервере для пары «пользователь × проект» (FR-TREE-14)."""

from __future__ import annotations

import pytest

from estimator.db.enums import SystemRole
from tests.integration.core.conftest import World

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-TREE-14")]


async def _project(world: World, actor) -> str:
    phases = await world.phases()
    response = await actor.post(
        "/projects",
        json={"name": "Портал", "customer": "ООО", "phase_ids": [str(phases["Разработка"])]},
    )
    return response.json()["project"]["id"]


async def test_state_roundtrip(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await _project(world, moderator)
    assert (await moderator.get(f"/me/view-state/{pid}")).json() == {"state": {}}
    state = {"expanded": ["a", "b"], "filters": {"discipline": "Бэкенд"}, "widths": {"title": 320}}
    saved = await moderator.put(f"/me/view-state/{pid}", json={"state": state})
    assert saved.status_code == 200
    assert saved.json() == {"state": state}
    # «другой браузер» — новая сессия того же пользователя видит то же состояние
    browser = await world.session_for(moderator.id, SystemRole.MODERATOR)
    assert (await browser.get(f"/me/view-state/{pid}")).json() == {"state": state}
    replaced = await browser.put(f"/me/view-state/{pid}", json={"state": {"expanded": []}})
    assert replaced.json() == {"state": {"expanded": []}}


async def test_state_limits_and_access(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    pid = await _project(world, moderator)
    big = {"blob": "x" * (64 * 1024)}
    response = await moderator.put(f"/me/view-state/{pid}", json={"state": big})
    assert (response.status_code, response.json()["code"]) == (413, "PAYLOAD_TOO_LARGE")
    stranger = await world.actor(SystemRole.MODERATOR)
    assert (await stranger.get(f"/me/view-state/{pid}")).status_code == 404
    assert (await stranger.put(f"/me/view-state/{pid}", json={"state": {}})).status_code == 404
    assert (await moderator.get("/me/view-state/not-a-uuid")).status_code == 404
