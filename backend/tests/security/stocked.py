"""Проект «со всем» для обходов TC-SEC-03 и TC-SEC-07: ставки и валюта USD, листья, вопрос,
вопрос заказчику, закрытая заметка с меткой, снимок; эксперт, ревьюер, пресейл."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.core.conftest import Actor, World, deliver_events
from tests.integration.core.test_nodes_api import Setup, _create, _setup

from estimator.db.enums import SystemRole

#: Текст закрытой заметки: не должен встретиться ни в одном ответе эксперту (TC-SEC-07).
NOTE_MARK = "ЗАМЕТКА-7f3a: заказчик готов на 2,5 млн"


@dataclass
class Stocked:
    s: Setup
    reviewer: Actor
    presale: Actor
    ids: dict[str, Any] = field(default_factory=dict)


async def stocked(world: World, db: AsyncSession) -> Stocked:
    s = await _setup(world, db)
    reviewer = await world.actor()
    presale = await world.actor(SystemRole.PRESALE)
    team = [
        {"user_id": str(s.moderator.id), "role": "moderator"},
        {"user_id": str(s.backend_expert.id), "role": "expert", "discipline_id": str(s.backend)},
        {"user_id": str(s.frontend_expert.id), "role": "expert", "discipline_id": str(s.frontend)},
        {"user_id": str(reviewer.id), "role": "expert", "discipline_id": str(s.backend),
         "is_reviewer": True},
        {"user_id": str(presale.id), "role": "presale"},
    ]  # fmt: skip
    put = await s.moderator.put(f"/projects/{s.pid}/members", json={"members": team})
    assert put.status_code == 200, put.text
    branch = await s.branch(db, s.backend)
    leaf = (await _create(s.backend_expert, s.pid, branch.id, title="Вход", o="8", r="12",
                          p="20")).json()["node"]  # fmt: skip
    money = await s.moderator.put(f"/projects/{s.pid}/money", json={
        "currency": "USD", "exchange_rate": "92.5",
        "rates": [{"discipline_id": str(s.backend), "rate_rub": "3000"},
                  {"discipline_id": str(s.frontend), "rate_rub": "2000"},
                  {"discipline_id": None, "rate_rub": "2500"}],
    })  # fmt: skip
    assert money.status_code == 200, money.text
    asked = await s.backend_expert.post(f"/nodes/{leaf['id']}/messages", json={
        "body": "Нужен SSO?", "needs_answer": True,
        "addressees": [{"target_type": "user", "target_id": str(s.moderator.id)}],
    })  # fmt: skip
    assert asked.status_code == 201, asked.text
    cq = await s.backend_expert.post(f"/nodes/{leaf['id']}/messages", json={
        "body": "Протокол 1С?", "addressees": [{"target_type": "customer", "target_id": None}],
    })  # fmt: skip
    assert cq.status_code == 201, cq.text
    notes = []
    for body in ({"body": NOTE_MARK}, {"node_id": leaf["id"], "body": NOTE_MARK}):
        note = await s.moderator.post(f"/projects/{s.pid}/notes", json=body)
        assert note.status_code == 201, note.text
        notes.append(note.json()["id"])
    spare = (await _create(s.backend_expert, s.pid, branch.id, title="Старое", o="1", r="2",
                           p="3")).json()["node"]  # fmt: skip
    trashed = await s.backend_expert.delete(f"/nodes/{spare['id']}")
    assert trashed.status_code == 200, trashed.text
    doc = await s.moderator.post(f"/projects/{s.pid}/documents", files={
        "file": ("ТЗ.pdf", b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n", "application/octet-stream"),
    })  # fmt: skip
    assert doc.status_code == 201, doc.text
    plain = await world.actor()
    snap = await s.moderator.post(f"/projects/{s.pid}/snapshots", json={"name": "Версия 1"})
    assert snap.status_code == 201, snap.text
    await deliver_events(db)
    ids = {"project": s.pid, "node": leaf["id"], "message": asked.json()["id"],
           "snapshot": snap.json()["id"], "tab": "readiness", "thread": asked.json()["thread_id"],
           "cq_thread": cq.json()["thread_id"], "note": notes[0], "user": plain.id,
           "phase": branch.phase_id, "discipline": s.backend, "section": "security",
           "batch": trashed.json()["batch_id"], "document": doc.json()["id"]}  # fmt: skip
    return Stocked(s, reviewer, presale, ids)
