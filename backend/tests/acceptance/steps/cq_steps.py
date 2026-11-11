"""QA-016 · шаги сценариев вопросов заказчику (SPEC 17.2): G-17 «Правка после отправки», G-22
«Автор закрывает отвеченный вопрос заказчику»."""

from __future__ import annotations

import uuid

from pytest_bdd import given, parsers, then, when
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli.seed_demo import _principal
from estimator.db.models.discussions import Thread
from estimator.services.customer_questions import flow
from tests.acceptance.steps.common import Scene, aio
from tests.integration.core.conftest import World
from tests.integration.core.test_customer_questions_api import _ask, _with_presale
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

STATUSES = {"отправлен": "sent", "отвечен": "answered"}


async def _question(world: World, db: AsyncSession, scene: Scene, number: str, status: str) -> None:
    """Вопрос эксперта Бэкенда с номером ``В-NNN`` (до него — NNN − 1 других) в статусе."""
    s = scene.s = await _setup(world, db)
    presale = await _with_presale(world, s)
    branch = await s.branch(db, s.backend)
    leaf = await _leaf(s.backend_expert, s, branch.id, "Обмен с 1С", o="40", r="60", p="100")
    wanted = int(number.removeprefix("В-"))
    for n in range(1, wanted):
        await _ask(s.backend_expert, leaf["id"], f"Вопрос {n}?")
    asked = await _ask(s.backend_expert, leaf["id"], "Протокол обмена с 1С?")
    tid = asked["thread_id"]
    await flow.mark_sent(db, _principal(presale.id, "presale", "Пресейл"), s.pid, [uuid.UUID(tid)])
    if STATUSES[status] == "answered":
        answered = await presale.post(f"/threads/{tid}/answer", json={"body": "REST, JSON"})
        assert answered.status_code == 200, answered.text
    thread = await db.get(Thread, uuid.UUID(tid), populate_existing=True)
    assert thread is not None
    assert (f"В-{thread.customer_question_no:03d}", str(thread.customer_status)) == (
        number, STATUSES[status],
    )  # fmt: skip
    scene.data |= {"tid": tid, "presale": presale, "number": number}


@given(parsers.parse("вопрос {number} автора-эксперта в статусе «{status}»"))
@aio
async def question_of_author(
    world: World, db_session: AsyncSession, scene: Scene, number: str, status: str
) -> None:
    await _question(world, db_session, scene, number, status)


@given(parsers.parse("вопрос {number} эксперта И. Иванова в статусе «{status}»"))
@aio
async def question_of_ivanov(
    world: World, db_session: AsyncSession, scene: Scene, number: str, status: str
) -> None:
    await _question(world, db_session, scene, number, status)


@when("автор пытается изменить текст")
@aio
async def author_edits(scene: Scene) -> None:
    scene.responses["edit"] = await scene.s.backend_expert.patch(
        f"/threads/{scene.data['tid']}/question", json={"body": "Другой текст"}
    )


@then("ответ 403")
def forbidden(scene: Scene) -> None:
    assert scene.responses["edit"].status_code == 403, scene.responses["edit"].text


@when("пресейл изменяет текст")
@aio
async def presale_edits(scene: Scene) -> None:
    scene.responses["edit"] = await scene.data["presale"].patch(
        f"/threads/{scene.data['tid']}/question", json={"body": "Протокол обмена (REST или файлы)?"}
    )
    assert scene.responses["edit"].status_code == 200, scene.responses["edit"].text


@then("вопрос помечен «изменён после отправки»")
def marked_edited(scene: Scene) -> None:
    assert scene.responses["edit"].json()["edited_after_sent"] is True


@then(parsers.parse("номер {number} сохраняется"))
@aio
async def number_kept(scene: Scene, number: str) -> None:
    s = scene.s
    listed = (await s.moderator.get(f"/projects/{s.pid}/customer-questions")).json()["items"]
    [item] = [i for i in listed if i["thread"]["id"] == scene.data["tid"]]
    assert f"В-{item['thread']['customer_question_no']:03d}" == number


@when("Иванов нажимает «Решено»")
@aio
async def author_resolves(scene: Scene) -> None:
    scene.responses["resolve"] = await scene.s.backend_expert.post(
        f"/threads/{scene.data['tid']}/resolve", json={}
    )


@then("вопрос переходит в «решён»")
def resolved(scene: Scene) -> None:
    response = scene.responses["resolve"]
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["customer_status"]) == ("resolved", "closed")
