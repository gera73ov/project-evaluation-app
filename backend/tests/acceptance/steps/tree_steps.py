"""QA-014 · шаги сценариев дерева (SPEC 17.2) на уровне API: G-01, G-02 «Сброс «готово» при
правке», G-07 «Множитель», G-13 «Исключение из проекта при открытой вкладке», G-14 «Оставить
моё», G-15, G-16 «Корзина», G-23, G-24 «Разбиение и сворачивание листа».

Интерфейсные части («плашка ×12», диалог конфликта, сообщение во вкладке) проверяют сценарии
Playwright (QA-018); здесь — данные API, по которым интерфейс их показывает.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pytest_bdd import given, parsers, then, when
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import BranchStatusValue, NodeKind, ProjectRole, SystemRole
from estimator.db.models.dictionaries import Discipline, Phase
from estimator.db.models.discussions import Notification
from estimator.db.models.projects import BranchStatus
from estimator.db.models.tree import Node, NodeHistory
from estimator.db.models.users import User
from estimator.realtime.bus.memory import validate_event
from estimator.services.trash.tasks import purge
from tests.acceptance.steps.common import Scene, aio
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import Setup, _create, _patch, _setup
from tests.integration.rt.conftest import Stage

NOTIFICATIONS = Path(__file__).resolve().parents[4] / "contracts" / "notifications.yaml"


async def _project(world: World, db: AsyncSession, scene: Scene) -> Setup:
    if scene.s is None:
        scene.s = await _setup(world, db)
    return scene.s


async def _branch(db: AsyncSession, s: Setup, phase: str = "Разработка") -> Node:
    phase_id = await db.scalar(select(Phase.id).where(Phase.name == phase))
    node = await db.scalar(
        select(Node).where(
            Node.project_id == s.pid,
            Node.discipline_id == s.backend,
            Node.phase_id == phase_id,
            Node.kind == NodeKind.DISCIPLINE,
        )
    )
    assert node is not None
    return node


async def _node(db: AsyncSession, node_id: Any) -> Node:
    node = await db.get(Node, uuid.UUID(str(node_id)), populate_existing=True)
    assert node is not None
    return node


async def _leaf(scene: Scene, parent: Any, title: str, **figures: Any) -> dict[str, Any]:
    s = scene.s
    created = await _create(s.backend_expert, s.pid, parent, title=title, **figures)
    assert created.status_code == 201, created.text
    scene.nodes[title] = created.json()["node"]
    return scene.nodes[title]


async def _edit(scene: Scene, db: AsyncSession, title: str, actor: Any = None, **changes: Any):  # type: ignore[no-untyped-def]
    node = await _node(db, scene.nodes[title]["id"])
    return await _patch(actor or scene.s.backend_expert, node.id, node.version, **changes)


async def _branch_status(db: AsyncSession, s: Setup, branch: Node) -> BranchStatusValue:
    row = await db.get(BranchStatus, (s.pid, branch.phase_id, s.backend), populate_existing=True)
    assert row is not None
    return row.status


def _hours(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", "."))


# --- G-01, G-02: сброс «готово» -----------------------------------------------------------------


@given("ветка «Разработка › Бэкенд» в статусе «готово»")
@aio
async def branch_done(world: World, db_session: AsyncSession, scene: Scene) -> None:
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    scene.data["branch"] = branch
    leaf = await _leaf(scene, branch.id, "Авторизация", o="8", r="12", p="20")
    reviewed = await s.moderator.post(f"/nodes/{leaf['id']}/review", json={"reviewed": True})
    assert reviewed.status_code == 200, reviewed.text
    done = await s.backend_expert.put(
        f"/projects/{s.pid}/branches/{branch.phase_id}/{s.backend}/status", json={"status": "done"}
    )
    assert done.status_code == 200, done.text
    assert await _branch_status(db_session, s, branch) is BranchStatusValue.DONE


@given(parsers.parse("эксперт Бэкенда открыл лист «{title}» с оценкой {o:d}–{r:d}–{p:d}"))
@aio
async def expert_opened_leaf(scene: Scene, title: str, o: int, r: int, p: int) -> None:
    s = scene.s
    tree = await s.backend_expert.get(f"/projects/{s.pid}/tree")
    assert tree.status_code == 200, tree.text
    [node] = [n for n in tree.json()["nodes"] if n["title"] == title]
    assert tuple(_hours(node[k]) for k in ("o", "r", "p")) == (o, r, p)
    assert node["reviewed_by"] is not None


@when(parsers.parse("эксперт меняет R на {value:d}"))
@aio
async def expert_changes_r(db_session: AsyncSession, scene: Scene, value: int) -> None:
    scene.responses["edit"] = await _edit(scene, db_session, "Авторизация", r=str(value))
    assert scene.responses["edit"].status_code == 200, scene.responses["edit"].text


@when(parsers.parse("эксперт меняет комментарий листа «{title}»"))
@aio
async def expert_changes_comment(db_session: AsyncSession, scene: Scene, title: str) -> None:
    lines = [{"tag_id": None, "text": "Через SSO заказчика"}]
    scene.responses["edit"] = await _edit(scene, db_session, title, comment_lines=lines)
    assert scene.responses["edit"].status_code == 200, scene.responses["edit"].text


@then("ветка «Разработка › Бэкенд» переходит в статус «черновик»")
@aio
async def branch_back_to_draft(db_session: AsyncSession, scene: Scene) -> None:
    branch = scene.data["branch"]
    assert await _branch_status(db_session, scene.s, branch) is BranchStatusValue.DRAFT
    assert scene.responses["edit"].json()["branch_status"]["status"] == "draft"


@then(parsers.parse("модератор получает уведомление «{text}»"))
@aio
async def moderator_notified(db_session: AsyncSession, scene: Scene, text: str) -> None:
    s = scene.s
    [note] = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == s.moderator.id,
                Notification.kind == "branch_back_to_draft",
            )
        )
    ).all()
    kinds = yaml.safe_load(NOTIFICATIONS.read_text(encoding="utf-8"))["kinds"]
    template = kinds["branch_back_to_draft"]["text"].strip("«»")
    discipline = await db_session.get(Discipline, uuid.UUID(note.payload["discipline_id"]))
    phase = await db_session.get(Phase, uuid.UUID(note.payload["phase_id"]))
    assert discipline is not None
    assert phase is not None
    shown = template.replace("<дисциплина>", discipline.name).replace("<фаза>", phase.name)
    assert shown == text
    listed = (await s.moderator.get("/notifications")).json()["items"]
    assert "branch_back_to_draft" in [n["kind"] for n in listed]


@then(parsers.parse("у листа «{title}» снимается отметка «Проверено»"))
@aio
async def review_removed(db_session: AsyncSession, scene: Scene, title: str) -> None:
    node = await _node(db_session, scene.nodes[title]["id"])
    assert node.reviewed_by is None
    assert scene.responses["edit"].json()["node"]["reviewed_by"] is None


@then("статус ветки остаётся «готово»")
@aio
async def branch_still_done(db_session: AsyncSession, scene: Scene) -> None:
    assert await _branch_status(db_session, scene.s, scene.data["branch"]) is BranchStatusValue.DONE
    assert scene.responses["edit"].json().get("branch_status") is None


@then("отметка «Проверено» у листа сохраняется")
@aio
async def review_kept(db_session: AsyncSession, scene: Scene) -> None:
    node = await _node(db_session, scene.nodes["Авторизация"]["id"])
    assert node.reviewed_by == scene.s.moderator.id


# --- G-07: множитель ----------------------------------------------------------------------------


@given(parsers.parse("лист «{title}» с оценкой {o:d}–{r:d}–{p:d}"))
@aio
async def leaf_with_estimate(
    world: World, db_session: AsyncSession, scene: Scene, title: str, o: int, r: int, p: int
) -> None:
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    await _leaf(scene, branch.id, title, o=str(o), r=str(r), p=str(p))
    scene.data["leaf"] = title


@when(parsers.parse("эксперт ставит множитель {value:d}"))
@aio
async def set_multiplier(db_session: AsyncSession, scene: Scene, value: int) -> None:
    response = await _edit(scene, db_session, scene.data["leaf"], multiplier=value)
    assert response.status_code == 200, response.text
    scene.nodes[scene.data["leaf"]] = response.json()["node"]


@then(parsers.parse("Σ E листа равна {value}"))
def leaf_e(scene: Scene, value: str) -> None:
    assert _hours(scene.nodes[scene.data["leaf"]]["e"]) == _hours(value)


@then(parsers.parse("σ листа равна {value}"))
def leaf_sigma(scene: Scene, value: str) -> None:
    assert _hours(scene.nodes[scene.data["leaf"]]["sigma"]) == _hours(value)


@then(parsers.parse("множитель показан выделенной плашкой «×{value:d}»"))
@aio
async def multiplier_badge(scene: Scene, value: int) -> None:
    """Плашку «×N» рисует интерфейс (QA-018) по полю ``multiplier`` узла дерева."""
    s = scene.s
    tree = (await s.backend_expert.get(f"/projects/{s.pid}/tree")).json()
    [node] = [n for n in tree["nodes"] if n["id"] == scene.nodes[scene.data["leaf"]]["id"]]
    assert node["multiplier"] == value


# --- G-13: исключение из проекта при открытой вкладке -------------------------------------------


@given("эксперт открыл проект «Портал дилеров»")
@aio
async def expert_opened_project(stage: Stage, scene: Scene) -> None:
    project = await stage.project()
    backend = await stage.discipline()
    expert_id, expert = await stage.user(member=(project, ProjectRole.EXPERT, backend))
    moderator_id, moderator = await stage.user(
        SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None)
    )
    tab = await stage.connect(expert)
    assert (await tab.subscribe(project.id))["type"] == "ack"
    scene.data |= {"project": project, "tab": tab, "expert_id": expert_id,
                   "moderator": (moderator_id, moderator)}  # fmt: skip


@when("модератор исключает его из команды")
@aio
async def moderator_removes_expert(stage: Stage, scene: Scene) -> None:
    project = scene.data["project"]
    moderator_id, moderator = scene.data["moderator"]
    team = [{"user_id": str(moderator_id), "role": "moderator"}]
    scene.data["removed_at"] = dt.datetime.now(dt.UTC)
    response = await stage.rest(
        "PUT", moderator, f"/projects/{project.id}/members", json={"members": team}
    )
    assert response.status_code == 200, response.text


@then(parsers.parse("в течение {seconds:d} секунд вкладка эксперта получает access.revoked"))
@aio
async def tab_revoked(scene: Scene, seconds: int) -> None:
    event = await scene.data["tab"].event("access.revoked", within=seconds)
    elapsed = dt.datetime.now(dt.UTC) - scene.data["removed_at"]
    assert elapsed < dt.timedelta(seconds=seconds)
    validate_event(event)
    assert event["data"] == {
        "project_id": str(scene.data["project"].id),
        "reason": "removed_from_team",
    }
    scene.data["revoked"] = event


@then(parsers.parse("показывает «{message}»"))
def tab_shows(scene: Scene, message: str) -> None:
    """Сообщение показывает интерфейс (QA-018) по событию; текст события — из контракта."""
    schema = Path(NOTIFICATIONS).with_name("ws-events.schema.json").read_text(encoding="utf-8")
    assert f'"title": "{message} — клиент закрывает проект"' in schema
    assert scene.data["revoked"]["event"] == "access.revoked"


# --- G-14: «Оставить моё» -----------------------------------------------------------------------


@given(parsers.parse("эксперты А и Б открыли лист с R = {r:d} (версия {version:d})"))
@aio
async def two_experts_opened(
    world: World, db_session: AsyncSession, scene: Scene, r: int, version: int
) -> None:
    s = await _project(world, db_session, scene)
    second = await world.actor()
    team = (await s.moderator.get(f"/projects/{s.pid}/members")).json()["items"]
    members = [{"user_id": m["user"]["id"], "role": m["role"],
                "discipline_id": m["discipline_id"]} for m in team]  # fmt: skip
    members.append({"user_id": str(second.id), "role": "expert", "discipline_id": str(s.backend)})
    assert (
        await s.moderator.put(f"/projects/{s.pid}/members", json={"members": members})
    ).status_code == 200
    branch = await _branch(db_session, s)
    leaf = await _leaf(scene, branch.id, "Лист", o="8", r=str(r), p="20")
    for n in range(2, version + 1):  # правки названия: версия растёт, R не меняется
        edited = await _patch(s.backend_expert, leaf["id"], n - 1, title=f"Лист, правка {n}")
        assert edited.status_code == 200, edited.text
    node = await _node(db_session, leaf["id"])
    assert (node.version, node.r) == (version, Decimal(r))
    scene.data |= {"a": s.backend_expert, "b": second, "id": leaf["id"], "base": version}


@when(parsers.parse(
    "А сохраняет R = {a:d}, а затем Б сохраняет R = {b:d} с base_version {base:d}"
))  # fmt: skip
@aio
async def both_save(scene: Scene, a: int, b: int, base: int) -> None:
    first = await _patch(scene.data["a"], scene.data["id"], base, r=str(a))
    assert first.status_code == 200, first.text
    scene.responses["b"] = await _patch(scene.data["b"], scene.data["id"], base, r=str(b))
    scene.data["mine"] = b


@then(parsers.parse("Б получает 409 и диалог «Значение изменил А: {theirs:d}. Ваше: {mine:d}»"))
@aio
async def b_conflict(db_session: AsyncSession, scene: Scene, theirs: int, mine: int) -> None:
    """Диалог строится из ответа 409: кто изменил, текущее значение и своё (FR-TREE-32)."""
    response = scene.responses["b"]
    assert response.status_code == 409, response.text
    problem = response.json()
    assert problem["code"] == "FIELD_CONFLICT"
    [conflict] = problem["conflicts"]
    assert (conflict["field"], _hours(conflict["current"])) == ("r", theirs)
    author = await db_session.get(User, scene.data["a"].id)
    assert author is not None
    assert conflict["changed_by"] == author.full_name
    assert scene.data["mine"] == mine
    scene.data["current_version"] = problem["current_version"]


@when("Б нажимает «Оставить моё»")
@aio
async def keep_mine(scene: Scene) -> None:
    """«Оставить моё» — повтор правки с текущей версией узла."""
    again = await _patch(
        scene.data["b"], scene.data["id"], scene.data["current_version"], r=str(scene.data["mine"])
    )
    assert again.status_code == 200, again.text


@then(parsers.parse("R = {r:d} и в истории две правки"))
@aio
async def r_and_history(db_session: AsyncSession, scene: Scene, r: int) -> None:
    node = await _node(db_session, scene.data["id"])
    assert node.r == Decimal(r)
    changes = (
        await db_session.scalars(
            select(NodeHistory.changes).where(
                NodeHistory.node_id == node.id, NodeHistory.node_version > scene.data["base"]
            )
        )
    ).all()
    assert [c["r"][1] for c in changes if "r" in c] == ["16", "18"]


# --- G-15, G-16: корзина ------------------------------------------------------------------------


@given(parsers.parse("узел «{title}» удалён из ветки «Разработка › Бэкенд»"))
@aio
async def node_deleted(world: World, db_session: AsyncSession, scene: Scene, title: str) -> None:
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    leaf = await _leaf(scene, branch.id, title, o="1", r="2", p="3")
    deleted = await s.backend_expert.delete(f"/nodes/{leaf['id']}")
    assert deleted.status_code == 200, deleted.text
    scene.data |= {"branch": branch, "batch": deleted.json()["batch_id"], "id": leaf["id"]}


@given("ветка переведена в «не нужно»")
@aio
async def branch_not_needed(scene: Scene) -> None:
    s, branch = scene.s, scene.data["branch"]
    response = await s.moderator.put(
        f"/projects/{s.pid}/branches/{branch.phase_id}/{s.backend}/status",
        json={"status": "not_needed"},
    )
    assert response.status_code == 200, response.text


@when("модератор восстанавливает узел")
@aio
async def moderator_restores(scene: Scene) -> None:
    s = scene.s
    scene.responses["restore"] = await s.moderator.post(
        f"/trash/{scene.data['batch']}/restore", json={}
    )


@then("система предлагает выбрать другое место в дисциплине Бэкенд")
@aio
async def offers_other_place(db_session: AsyncSession, scene: Scene) -> None:
    s = scene.s
    problem = scene.responses["restore"]
    assert problem.status_code == 409, problem.text
    assert (problem.json()["code"], problem.json()["reason"], problem.json()["discipline_id"]) == (
        "RESTORE_TARGET_UNAVAILABLE", "branch_not_needed", str(s.backend),
    )  # fmt: skip
    other = await _branch(db_session, s, "Тестирование")  # то же место в другой фазе — можно
    moved = await s.moderator.post(
        f"/trash/{scene.data['batch']}/restore", json={"target_parent_id": str(other.id)}
    )
    assert moved.status_code == 200, moved.text
    assert (await _node(db_session, scene.data["id"])).parent_id == other.id


@given(parsers.parse("узел удалён {days:d} день назад"))
@aio
async def node_deleted_days_ago(
    world: World, db_session: AsyncSession, scene: Scene, days: int
) -> None:
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    leaf = await _leaf(scene, branch.id, "Старое")
    deleted = await s.backend_expert.delete(f"/nodes/{leaf['id']}")
    assert deleted.status_code == 200, deleted.text
    now = dt.datetime.now(dt.UTC)
    await db_session.execute(
        update(Node)
        .where(Node.id == uuid.UUID(leaf["id"]))
        .values(deleted_at=now - dt.timedelta(days=days))
    )
    scene.data |= {"now": now, "batch": deleted.json()["batch_id"], "id": leaf["id"]}


@when("отработала ночная задача")
@aio
async def nightly_job(db_session: AsyncSession, scene: Scene) -> None:
    """Ночные задачи сценария: очистка корзины (G-16) и автоархивация (G-25)."""
    from estimator.services.projects.tasks import autoarchive

    now = scene.data.get("now") or dt.datetime.now(dt.UTC)
    scene.data["purged"] = await purge(db_session, now)
    scene.data["archived"] = await autoarchive(db_session, now=now)


@then("узла нет в корзине и восстановить его нельзя")
@aio
async def node_gone(db_session: AsyncSession, scene: Scene) -> None:
    s = scene.s
    assert scene.data["purged"] == 1
    assert await db_session.get(Node, uuid.UUID(scene.data["id"]), populate_existing=True) is None
    trash = (await s.moderator.get(f"/projects/{s.pid}/trash")).json()["items"]
    assert scene.data["batch"] not in [i["batch_id"] for i in trash]
    restore = await s.moderator.post(f"/trash/{scene.data['batch']}/restore", json={})
    assert restore.status_code == 404


# --- G-23, G-24: разбиение и сворачивание -------------------------------------------------------


@given(parsers.parse("лист «{title}» {o:d}–{r:d}–{p:d} ×{m:d}"))
@aio
async def leaf_with_multiplier(
    world: World, db_session: AsyncSession, scene: Scene, title: str, o: int, r: int, p: int,
    m: int,
) -> None:  # fmt: skip
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    leaf = await _leaf(scene, branch.id, title, o=str(o), r=str(r), p=str(p), multiplier=m)
    scene.data |= {"leaf": title, "e": leaf["e"]}


@when("эксперт выбирает «Разбить на части»")
@aio
async def split(db_session: AsyncSession, scene: Scene) -> None:
    node = await _node(db_session, scene.nodes[scene.data["leaf"]]["id"])
    response = await scene.s.backend_expert.post(
        f"/nodes/{node.id}/split", json={"base_version": node.version}
    )
    assert response.status_code == 200, response.text
    scene.responses["split"] = response


@then(parsers.parse("узел «{title}» имеет одного ребёнка «{child}» с {o:d}–{r:d}–{p:d}"))
def split_child(scene: Scene, title: str, child: str, o: int, r: int, p: int) -> None:
    nodes = scene.responses["split"].json()["nodes"]
    node_id = scene.nodes[title]["id"]
    [kid] = [n for n in nodes if n["parent_id"] == node_id]
    assert kid["title"] == child
    assert tuple(_hours(kid[k]) for k in ("o", "r", "p")) == (o, r, p)
    scene.data["after"] = next(n for n in nodes if n["id"] == node_id)


@then("E узла не изменилось")
def e_unchanged(scene: Scene) -> None:
    assert _hours(scene.data["after"]["e"]) == _hours(scene.data["e"])


@given(parsers.parse("узел с детьми {o1:d}–{r1:d}–{p1:d} ×{m1:d} и {o2:d}–{r2:d}–{p2:d} ×{m2:d}"))
@aio
async def node_with_children(
    world: World, db_session: AsyncSession, scene: Scene,
    o1: int, r1: int, p1: int, m1: int, o2: int, r2: int, p2: int, m2: int,
) -> None:  # fmt: skip
    s = await _project(world, db_session, scene)
    branch = await _branch(db_session, s)
    group = await _leaf(scene, branch.id, "Модуль")
    await _leaf(scene, group["id"], "A", o=str(o1), r=str(r1), p=str(p1), multiplier=m1)
    await _leaf(scene, group["id"], "B", o=str(o2), r=str(r2), p=str(p2), multiplier=m2)
    scene.data["group"] = group["id"]


@when("эксперт выбирает «Свернуть в лист»")
@aio
async def collapse(db_session: AsyncSession, scene: Scene) -> None:
    s, gid = scene.s, scene.data["group"]
    hint = await s.backend_expert.get(f"/nodes/{gid}/collapse")
    assert hint.status_code == 200, hint.text
    scene.data["hint"] = hint.json()
    node = await _node(db_session, gid)
    done = await s.backend_expert.post(
        f"/nodes/{gid}/collapse", json={"base_version": node.version}
    )
    assert done.status_code == 200, done.text
    scene.responses["collapse"] = done


@then(parsers.parse("предложено {o:d}–{r:d}–{p:d} ×{m:d}"))
def collapse_hint(scene: Scene, o: int, r: int, p: int, m: int) -> None:
    hint = scene.data["hint"]
    assert tuple(_hours(hint[k]) for k in ("o", "r", "p")) == (o, r, p)
    assert hint["multiplier"] == m
    node = {n["id"]: n for n in scene.responses["collapse"].json()["nodes"]}[scene.data["group"]]
    assert tuple(_hours(node[k]) for k in ("o", "r", "p")) == (o, r, p)


@then("дети ушли в корзину одним пакетом")
@aio
async def children_in_one_batch(scene: Scene) -> None:
    s, body = scene.s, scene.responses["collapse"].json()
    kids = {scene.nodes["A"]["id"], scene.nodes["B"]["id"]}
    assert set(body["deleted_ids"]) == kids
    trash = (await s.moderator.get(f"/projects/{s.pid}/trash")).json()["items"]
    assert [i["batch_id"] for i in trash] == [body["batch_id"]]
