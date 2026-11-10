"""CORE-050/051/053: статистика — сетка готовности с флажками, итоги, контрольные соотношения,
объёмы, кандидаты, списки по меткам, «Проверено»; деньги только ролям с деньгами (G-03);
«Напомнить не начавшим» не чаще раза в сутки (10.1, 11.8–11.11, FR-REV-03, GAP-08)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import CommentTagCategory, ProjectRole
from estimator.db.models.dictionaries import CommentTag
from estimator.db.models.projects import ProjectMember
from estimator.db.models.tree import Node
from estimator.notifications import tasks as mail_tasks
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import _patch, _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("10.1")]


async def _version(db: AsyncSession, node_id: str) -> int:
    return (await db.scalars(select(Node.version).where(Node.id == node_id))).one()


@pytest.mark.spec("FR-REV-03")
@pytest.mark.spec("BR-PRJ-08")
async def test_stats(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    a = await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    await _leaf(s.backend_expert, s, branch.id, "Отчёты", o="1", r="2", p="30")
    risk = (
        await db_session.scalars(
            select(CommentTag.id).where(CommentTag.category == CommentTagCategory.RISK)
        )
    ).first()
    line = {"tag_id": str(risk), "text": "Нет стенда"}
    base = await _version(db_session, a["id"])
    commented = await _patch(s.backend_expert, a["id"], base, comment_lines=[line])
    assert commented.status_code == 200, commented.text
    await s.moderator.put(
        f"/projects/{s.pid}/money",
        json={"rates": [{"discipline_id": str(s.backend), "rate_rub": "3000"},
                        {"discipline_id": str(s.frontend), "rate_rub": "2000"},
                        {"discipline_id": None, "rate_rub": "2500"}]},
    )  # fmt: skip
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == s.pid, ProjectMember.discipline_id == s.frontend
        )
    )
    await db_session.execute(
        text("UPDATE projects SET deadline = :d WHERE id = :p"),
        {"d": dt.date.today() - dt.timedelta(days=10), "p": s.pid},
    )

    response = await s.moderator.get(f"/projects/{s.pid}/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    cells = {(c["phase_id"], c["discipline_id"]): c for c in body["readiness"]}
    assert len(cells) == 4  # 2 фазы работ × 2 дисциплины
    mine = cells[(str(branch.phase_id), str(s.backend))]
    assert mine["status"] == "draft"
    assert float(mine["e"]) > 0
    assert "wide_fork" in mine["flags"]
    assert mine["last_change_at"] is not None
    front = cells[(str(branch.phase_id), str(s.frontend))]
    assert "no_expert" in front["flags"]
    assert "overdue" in front["flags"]
    assert front["overdue_working_days"] > 0

    tree = (await s.moderator.get(f"/projects/{s.pid}/tree")).json()["totals"]
    assert body["totals"]["total"]["e"] == tree["total"]["e"]
    backend_row = next(
        d for d in body["totals"]["by_discipline"] if d["discipline_id"] == str(s.backend)
    )
    assert backend_row["share_pct"] == "100"
    assert body["volumes"][0]["count"] == 2
    assert body["candidates"]["large"][0]["node_id"] == a["id"]
    risks = next(t for t in body["tag_lists"] if t["category"] == "risk")["items"]
    assert [(i["node_id"], i["text"]) for i in risks] == [(a["id"], "Нет стенда")]
    assert risks[0]["path"][-1] == "Вход"
    reviewed = {r["discipline_id"]: r for r in body["reviewed"]}
    assert reviewed[str(s.backend)]["reviewed_pct"] == "0"
    assert reviewed[str(s.frontend)]["reviewed_pct"] is None
    money = body["money"]
    costs = {c["discipline_id"]: c["cost_rub"] for c in money["cost_by_discipline"]}
    assert costs[str(s.backend)] is not None
    assert set(money["figures"]) == {"e", "p80", "p90"}

    expert = await s.backend_expert.get(f"/projects/{s.pid}/stats")
    assert expert.status_code == 200, expert.text
    assert "money" not in expert.json()
    assert "cost" not in expert.text


@pytest.mark.spec("FR-NOTIF-03")
async def test_remind(
    world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mail_tasks.send_email, "delay", lambda *args: sent.append(args))
    s = await _setup(world, db_session)
    for actor in (s.backend_expert, s.frontend_expert):
        await db_session.execute(
            text("UPDATE users SET email = :e WHERE id = :u"),
            {"e": f"u{actor.id.hex[:12]}@corp.ru", "u": actor.id},
        )
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="8", r="12", p="20")
    # бэкенд начал одну фазу, но не вторую — тоже адресат
    url = f"/projects/{s.pid}/remind"
    assert (await s.backend_expert.post(url)).status_code == 403
    first = await s.moderator.post(url)
    assert first.status_code == 200, first.text
    assert first.json() == {"sent_to": 2}
    assert {m[0] for m in sent} == {"remind_not_started"}
    assert all("Вход" not in str(m[2]) for m in sent)  # без названий узлов (FR-NOTIF-03)
    again = await s.moderator.post(url)
    assert (again.status_code, again.json()["code"]) == (429, "REMIND_TOO_OFTEN")
    assert int(again.headers["Retry-After"]) > 0
    assert len(sent) == 2


async def test_remind_nobody(world: World, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == s.pid, ProjectMember.role == ProjectRole.EXPERT
        )
    )
    nobody = await s.moderator.post(f"/projects/{s.pid}/remind")
    assert nobody.json() == {"sent_to": 0}
    assert (await s.moderator.post(f"/projects/{s.pid}/remind")).json() == {"sent_to": 0}
