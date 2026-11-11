"""CORE-044 (TC-CQ-01): вопросы заказчику — номер В-NNN, переходы статусов × роли, ответ
заказчика, правка после отправки, снятие с причиной, список с фильтрами."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli.seed_demo import _principal
from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.discussions import MessageHistory, Notification, Thread
from estimator.db.models.projects import Project
from estimator.realtime.bus.memory import InMemoryBus
from estimator.services.customer_questions import flow
from tests.integration.core.conftest import World, deliver_events
from tests.integration.core.test_nodes_api import Setup, _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-CQ-01"), pytest.mark.tc("TC-CQ-01")]

CUSTOMER = [{"target_type": "customer", "target_id": None}]


async def _with_presale(world: World, s: Setup):  # type: ignore[no-untyped-def]
    presale = await world.actor(SystemRole.PRESALE)
    team = [
        {"user_id": str(s.moderator.id), "role": "moderator"},
        {"user_id": str(s.backend_expert.id), "role": "expert", "discipline_id": str(s.backend)},
        {"user_id": str(s.frontend_expert.id), "role": "expert", "discipline_id": str(s.frontend)},
        {"user_id": str(presale.id), "role": "presale"},
    ]
    put = await s.moderator.put(f"/projects/{s.pid}/members", json={"members": team})
    assert put.status_code == 200, put.text
    return presale


async def _ask(actor, node_id: str, body: str = "Протокол 1С?") -> dict:  # type: ignore[no-untyped-def]
    r = await actor.post(f"/nodes/{node_id}/messages", json={"body": body, "addressees": CUSTOMER})
    assert r.status_code == 201, r.text
    return r.json()


async def _status(db: AsyncSession, thread_id: str) -> str:
    db.expire_all()
    return str((await db.get(Thread, uuid.UUID(thread_id))).customer_status)  # type: ignore[union-attr]


@pytest.mark.spec("BR-CQ-01")
@pytest.mark.spec("BR-CQ-02")
@pytest.mark.spec("FR-CQ-03")
async def test_customer_question_flow(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    s = await _setup(world, db_session)
    presale = await _with_presale(world, s)
    branch = await s.branch(db_session, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Обмен с 1С", o="40", r="60", p="100")

    q1 = await _ask(s.backend_expert, leaf["id"])
    tid = q1["thread_id"]
    q2 = await _ask(s.backend_expert, leaf["id"], "Формат файлов?")

    # автор правит «новый»; чужой эксперт — нет
    edit = f"/threads/{tid}/question"
    assert (await s.frontend_expert.patch(edit, json={"body": "x"})).status_code == 403
    assert (
        await s.backend_expert.patch(edit, json={"body": "Протокол обмена с 1С?"})
    ).status_code == 200

    # «новый» → «отправлен» (выгрузка EXP-007)
    sent = await flow.mark_sent(
        db_session, _principal(presale.id, "presale", "Пресейл"), s.pid, [uuid.UUID(tid)]
    )
    assert [str(t) for t in sent] == [tid]
    assert await _status(db_session, tid) == "sent"

    # после отправки автор не правит и не снимает; пресейл правит с пометкой
    frozen = await s.backend_expert.patch(edit, json={"body": "Другое"})
    assert (frozen.status_code, frozen.json()["code"]) == (403, "FORBIDDEN")
    assert (
        await s.backend_expert.patch(f"/messages/{q1['id']}", json={"body": "y"})
    ).status_code == 403
    no_withdraw = await s.backend_expert.post(f"/threads/{tid}/withdraw", json={"reason": "дубль"})
    assert no_withdraw.status_code == 403
    changed = await presale.patch(edit, json={"body": "Протокол обмена (REST или файлы)?"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["edited_after_sent"] is True
    reasons = (
        await db_session.scalars(
            select(MessageHistory.reason).where(MessageHistory.message_id == q1["id"])
        )
    ).all()
    assert sorted(str(r) for r in reasons) == ["edit", "edit_after_sent"]

    # ответ заказчика: только пресейл и модератор; «отправлен» → «отвечен»
    answer = f"/threads/{tid}/answer"
    assert (await s.backend_expert.post(answer, json={"body": "REST"})).status_code == 403
    answered = await presale.post(answer, json={"body": "REST, JSON"})
    assert answered.status_code == 200, answered.text
    assert (answered.json()["customer_status"], answered.json()["answered_at"] is not None) == (
        "answered",
        True,
    )
    kinds = await db_session.scalars(
        select(Notification.kind).where(Notification.user_id == s.backend_expert.id)
    )
    assert "answer_to_my_question" in list(kinds)
    again = await presale.post(answer, json={"body": "ещё"})
    assert (again.status_code, again.json()["code"]) == (409, "INVALID_TRANSITION")

    # «отвечен» → «решён»: автор может; переоткрыть — нет, пресейл — да
    closed = await s.backend_expert.post(f"/threads/{tid}/resolve", json={})
    assert closed.status_code == 200, closed.text
    assert (closed.json()["customer_status"], closed.json()["status"]) == ("closed", "resolved")
    assert (await s.backend_expert.post(f"/threads/{tid}/reopen")).status_code == 403
    reopened = await presale.post(f"/threads/{tid}/reopen")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["customer_status"] == "answered"

    # «новый» → «снят»: автор с причиной; номер сохраняется, новый вопрос — следующий номер
    tid2 = q2["thread_id"]
    no_reason = await s.backend_expert.post(f"/threads/{tid2}/withdraw", json={"reason": "  "})
    assert no_reason.status_code == 422
    gone = await s.backend_expert.post(f"/threads/{tid2}/withdraw", json={"reason": "Дубль"})
    assert gone.status_code == 200, gone.text
    assert (gone.json()["customer_status"], gone.json()["withdraw_reason"]) == (
        "withdrawn",
        "Дубль",
    )
    assert (await presale.post(f"/threads/{tid2}/answer", json={"body": "x"})).status_code == 409
    q3 = await _ask(s.moderator, leaf["id"], "Сроки?")
    numbers = (
        await db_session.scalars(
            select(Thread.customer_question_no)
            .where(Thread.project_id == s.pid)
            .order_by(Thread.customer_question_no)
        )
    ).all()
    assert numbers == [1, 2, 3]

    # список: фильтры, путь, ответ, курсор
    url = f"/projects/{s.pid}/customer-questions"
    listed = (await s.frontend_expert.get(url)).json()["items"]
    assert [i["thread"]["customer_question_no"] for i in listed] == [1, 2, 3]
    first = listed[0]
    assert first["path"][-1] == "Обмен с 1С"
    assert first["answer"]["kind"] == "customer_answer"
    assert listed[1]["answer"] is None
    only_new = (await s.moderator.get(url, params={"status": "new"})).json()["items"]
    assert [i["thread"]["id"] for i in only_new] == [q3["thread_id"]]
    other = (await s.moderator.get(url, params={"discipline_id": str(s.frontend)})).json()
    assert other["items"] == []
    paged = (await s.moderator.get(url, params={"limit": 2})).json()
    rest = (await s.moderator.get(url, params={"limit": 2, "cursor": paged["next_cursor"]})).json()
    assert [i["thread"]["customer_question_no"] for i in rest["items"]] == [3]

    await deliver_events(db_session)
    updates = [
        e for e in events.on(f"project:{s.pid}") if e["event"] == "customer_question.updated"
    ]
    assert [e["data"]["status"] for e in updates if e["data"]["thread_id"] == tid] == [
        "new",  # правка автором
        "sent",
        "sent",  # правка после отправки
        "answered",
        "closed",
        "answered",
    ]

    # «Архив»: статусы не меняются; «Завершена» — ответы ещё вносят
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.COMPLETED)
    )
    late = await presale.post(f"/threads/{q3['thread_id']}/answer", json={"body": "Июнь"})
    assert late.status_code == 200, late.text
    await db_session.execute(
        update(Project).where(Project.id == s.pid).values(status=ProjectStatus.ARCHIVED)
    )
    frozen_archive = await presale.post(f"/threads/{q3['thread_id']}/resolve", json={})
    assert frozen_archive.status_code == 409, frozen_archive.text
