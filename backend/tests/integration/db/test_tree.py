"""DB-006: ограничения дерева, история и журнал проекта только на INSERT, индекс загрузки 14.3."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import Discipline, NodeType, Phase
from estimator.db.models.projects import Project
from estimator.db.models.tree import ChangeLog, Node, NodeHistory, ProjectJournal, UserViewState
from estimator.db.models.users import User
from estimator.db.uuid7 import uuid7
from tests.integration.db.conftest import as_app
from tests.integration.db.test_users_constraints import _rejects

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.2")]


async def tree(session: AsyncSession) -> tuple[Project, Node, Node]:
    """Проект с фазой «Разработка» и веткой «Бэкенд»: (проект, узел фазы, узел ветки)."""
    project = Project(name="Портал дилеров", customer="ООО Ромашка", pm_percent=Decimal(18))
    session.add(project)
    await session.flush()
    phase = (await session.scalars(select(Phase).where(Phase.name == "Разработка"))).one()
    backend = (await session.scalars(select(Discipline).where(Discipline.name == "Бэкенд"))).one()
    phase_node = Node(
        project_id=project.id, kind="phase", phase_id=phase.id, title=phase.name, position="a0"
    )
    session.add(phase_node)
    await session.flush()
    branch = Node(
        project_id=project.id,
        parent_id=phase_node.id,
        kind="discipline",
        phase_id=phase.id,
        discipline_id=backend.id,
        title=backend.name,
        position="a0",
    )
    session.add(branch)
    await session.flush()
    return project, phase_node, branch


def item(branch: Node, **kw: object) -> Node:
    fields = {
        "project_id": branch.project_id,
        "parent_id": branch.id,
        "kind": "item",
        "phase_id": branch.phase_id,
        "discipline_id": branch.discipline_id,
        "title": "Авторизация",
        "position": "a0",
        **kw,
    }
    return Node(**fields)


async def test_item_accepts_valid_hours(db_session: AsyncSession) -> None:
    _, _, branch = await tree(db_session)
    node = item(branch, o=Decimal("0.5"), r=Decimal(4), p=Decimal("99999.5"), multiplier=10000)
    db_session.add(node)
    await db_session.flush()
    assert node.version == 1
    assert node.field_versions == {}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"o": Decimal("0.25")},  # шаг 0,5 (BR-CALC-03)
        {"p": Decimal(100000)},
        {"r": Decimal(-1)},
        {"multiplier": 0},
        {"multiplier": 10001},
        {"title": ""},
        {"title": "две\nстроки"},  # BR-TREE-07
        {"discipline_id": None},  # item без ветки
        {"parent_id": None},  # parent NULL только у фаз
        {"reviewed_at": func.now()},  # «Проверено» без проверяющего
        {"self_review": True},
        {"comment_lines": {"text": "не массив"}},
        {"deleted_at": func.now()},  # корзина без пакета
    ],
    ids=[
        "o-step",
        "p-max",
        "r-negative",
        "mult-0",
        "mult-max",
        "title-empty",
        "title-newline",
        "no-discipline",
        "no-parent",
        "reviewed-at",
        "self-review",
        "comment-object",
        "deleted-batch",
    ],
)
async def test_item_checks(db_session: AsyncSession, kwargs: dict) -> None:
    _, _, branch = await tree(db_session)
    await _rejects(db_session, item(branch, **kwargs))


async def test_phase_and_branch_rules(db_session: AsyncSession) -> None:
    project, phase_node, branch = await tree(db_session)
    work = (await db_session.scalars(select(NodeType).where(NodeType.is_system))).one()
    # вторая живая фаза и вторая живая ветка в проекте
    await _rejects(
        db_session,
        Node(
            project_id=project.id,
            kind="phase",
            phase_id=phase_node.phase_id,
            title="Ещё",
            position="b0",
        ),
    )
    await _rejects(db_session, item(branch, kind="discipline", parent_id=phase_node.id))
    # фаза не лист и не ветка; тип только у элемента
    await _rejects(
        db_session,
        Node(
            project_id=project.id,
            kind="phase",
            phase_id=phase_node.phase_id,
            title="Фаза",
            position="b0",
            o=Decimal(1),
        ),
    )
    await _rejects(db_session, item(branch, kind="discipline", type_id=work.id))
    # удалённая фаза не мешает живой с той же фазой (частичный индекс)
    phase_node.deleted_at = func.now()
    phase_node.deleted_batch_id = uuid7()
    await db_session.flush()
    db_session.add(
        Node(
            project_id=project.id,
            kind="phase",
            phase_id=phase_node.phase_id,
            title="Разработка",
            position="a1",
        )
    )
    await db_session.flush()


async def test_position_uses_c_collation(db_session: AsyncSession) -> None:
    """ARCH-04: ключи порядка сравниваются побайтно, «Z» < «a»."""
    _, _, branch = await tree(db_session)
    db_session.add_all([item(branch, position="a"), item(branch, position="Z")])
    await db_session.flush()
    positions = await db_session.scalars(
        select(Node.position).where(Node.parent_id == branch.id).order_by(Node.position)
    )
    assert list(positions) == ["Z", "a"]


async def _history(session: AsyncSession, node: Node) -> NodeHistory:
    row = NodeHistory(
        node_id=node.id,
        project_id=node.project_id,
        project_version=1,
        node_version=1,
        action="update",
        changes={"r": ["12", "16"]},
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE node_history SET changes = '{}'",
        "DELETE FROM node_history",
        "TRUNCATE node_history",
        "UPDATE project_journal SET action = 'x'",
        "DELETE FROM project_journal",
    ],
    ids=[
        "history-update",
        "history-delete",
        "history-truncate",
        "journal-update",
        "journal-delete",
    ],
)
@pytest.mark.spec("SEC-AUD-03")
async def test_history_is_insert_only(db_session: AsyncSession, statement: str) -> None:
    """G-5: история узлов и журнал проекта — только INSERT для роли приложения."""
    await as_app(db_session)
    project, _, branch = await tree(db_session)
    await _history(db_session, branch)
    db_session.add(ProjectJournal(project_id=project.id, action="project.settings", changes={}))
    await db_session.flush()
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_journal_money_keys_only_in_money_records(db_session: AsyncSession) -> None:
    project, _, _ = await tree(db_session)
    changes = {"rate_rub": ["2500", "3000"]}
    await _rejects(
        db_session, ProjectJournal(project_id=project.id, action="money.changed", changes=changes)
    )
    db_session.add(
        ProjectJournal(
            project_id=project.id, action="money.changed", is_money=True, changes=changes
        )
    )
    await db_session.flush()


@pytest.mark.spec("BR-PRJ-04")
async def test_project_delete_cascades_as_app(db_session: AsyncSession) -> None:
    """Каскад от проекта чистит дерево, историю и журнал, хотя у роли нет DELETE на историю."""
    user = User(login="t.tree", full_name="Эксперт", status="active")
    db_session.add(user)
    await db_session.flush()
    await as_app(db_session)
    project, _, branch = await tree(db_session)
    local_type = NodeType(
        name="Отчёт заказчика", icon="report", project_id=project.id, proposal_status="proposed"
    )
    db_session.add(local_type)
    await db_session.flush()
    leaf = item(branch, type_id=local_type.id)
    db_session.add(leaf)
    await db_session.flush()
    await _history(db_session, leaf)
    db_session.add_all(
        [
            ProjectJournal(project_id=project.id, action="project.created", changes={}),
            ChangeLog(project_id=project.id, version=1, event={"type": "node.created"}),
            UserViewState(user_id=user.id, project_id=project.id),
        ]
    )
    await db_session.flush()
    await db_session.delete(project)
    await db_session.flush()
    for model in (Node, NodeHistory, ProjectJournal, ChangeLog, UserViewState):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__


@pytest.mark.spec("14.3")
async def test_tree_query_uses_partial_index(db_session: AsyncSession) -> None:
    project, _, _ = await tree(db_session)
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = await db_session.scalars(
        text(
            "EXPLAIN SELECT id, parent_id, kind, phase_id, discipline_id, type_id, title, "
            "position, o, r, p, multiplier, comment_lines, reviewed_by, version FROM nodes "
            "WHERE project_id = :project_id AND deleted_at IS NULL "
            "ORDER BY parent_id NULLS FIRST, position"
        ),
        {"project_id": project.id},
    )
    assert "nodes_project_live_idx" in "\n".join(plan)
