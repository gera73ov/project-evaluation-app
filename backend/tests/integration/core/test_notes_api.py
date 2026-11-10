"""CORE-031: закрытые заметки — права, TOTP, заметки узла и проекта, правка, события только
в ``project:{id}:notes``, статус проекта (D-01)."""

from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project
from estimator.realtime.bus.memory import InMemoryBus
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_customer_questions_api import _with_presale
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-NOTE-01"), pytest.mark.spec("Q-03")]


@pytest.mark.spec("SEC-AUTHZ-04")
@pytest.mark.spec("FR-2FA-05")
async def test_notes_access(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    presale = await _with_presale(world, s)
    url = f"/projects/{s.pid}/notes"

    for expert in (s.backend_expert, s.frontend_expert):
        denied = await expert.get(url)
        assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
        assert (await expert.post(url, json={"body": "x"})).status_code == 403

    no_totp = await world.session_for(s.moderator.id, SystemRole.MODERATOR, mfa=False)
    blocked = await no_totp.get(url)
    assert (blocked.status_code, blocked.json()["code"]) == (403, "TOTP_REQUIRED")

    made = await presale.post(url, json={"body": "Заказчик торгуется, держим P80"})
    assert made.status_code == 201, made.text
    note = made.json()
    assert (note["node_id"], note["author"]["id"], note["edited_at"]) == (
        None,
        str(presale.id),
        None,
    )

    head = await world.actor(SystemRole.PRESALE_HEAD)
    seen = await head.get(url)
    assert seen.status_code == 200, seen.text
    assert [n["id"] for n in seen.json()["items"]] == [note["id"]]
    assert (await head.post(url, json={"body": "x"})).status_code == 403
    assert (await head.patch(f"/notes/{note['id']}", json={"body": "x"})).status_code == 403
    assert (
        await s.backend_expert.patch(f"/notes/{note['id']}", json={"body": "x"})
    ).status_code == 403


async def test_notes_crud(world: World, db_session: AsyncSession, events: InMemoryBus) -> None:
    s = await _setup(world, db_session)
    presale = await _with_presale(world, s)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Обмен с 1С", o="40", r="60", p="100")
    url = f"/projects/{s.pid}/notes"

    top = (await s.moderator.post(url, json={"body": "Бюджет до 2 млн"})).json()
    at_node = await s.moderator.post(url, json={"node_id": leaf["id"], "body": "Можно урезать"})
    assert at_node.status_code == 201, at_node.text
    assert at_node.json()["node_id"] == leaf["id"]

    blank = await s.moderator.post(url, json={"body": "   "})
    assert (blank.status_code, blank.json()["code"]) == (422, "VALIDATION_FAILED")
    long = await s.moderator.post(url, json={"body": "я" * 4001})
    assert long.status_code == 422
    stranger = await s.moderator.post(url, json={"node_id": str(s.pid), "body": "x"})
    assert (stranger.status_code, stranger.json()["code"]) == (422, "VALIDATION_FAILED")

    only_node = (await s.moderator.get(url, params={"node_id": leaf["id"]})).json()["items"]
    assert [n["id"] for n in only_node] == [at_node.json()["id"]]
    first = (await s.moderator.get(url, params={"limit": 1})).json()
    assert [n["id"] for n in first["items"]] == [top["id"]]
    rest = (await s.moderator.get(url, params={"limit": 1, "cursor": first["next_cursor"]})).json()
    assert ([n["id"] for n in rest["items"]], rest["next_cursor"]) == ([at_node.json()["id"]], None)

    # править может любой с notes.write, не только автор
    edited = await presale.patch(f"/notes/{top['id']}", json={"body": "Бюджет до 2,5 млн"})
    assert edited.status_code == 200, edited.text
    assert (edited.json()["body"], edited.json()["edited_at"] is not None) == (
        "Бюджет до 2,5 млн",
        True,
    )
    assert edited.json()["author"]["id"] == str(s.moderator.id)

    # заметки — не обсуждения: в ленте узла их нет
    feed = (await s.backend_expert.get(f"/nodes/{leaf['id']}/messages")).json()
    assert "Можно урезать" not in str(feed)
    tree = (await s.backend_expert.get(f"/projects/{s.pid}/tree")).json()
    assert "Можно урезать" not in str(tree)

    await deliver_events(db_session)
    notes = events.on(f"project:{s.pid}:notes")
    assert [e["event"] for e in notes] == ["note.created", "note.created", "note.updated"]
    assert notes[-1]["data"]["note"]["body"] == "Бюджет до 2,5 млн"
    assert not [e for e in events.on(f"project:{s.pid}") if e["event"].startswith("note.")]

    # «Завершена» — только чтение (D-01)
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.COMPLETED)
    )
    late = await s.moderator.post(url, json={"body": "поздно"})
    assert (late.status_code, late.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")
    assert (await s.moderator.get(url)).status_code == 200
