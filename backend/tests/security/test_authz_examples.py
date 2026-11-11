"""QA-003 · SEC-AUTHZ-05: явные кейсы таблицы ``authz_examples`` (contracts/permissions.yaml).

Каждая строка таблицы — своя проверка ниже (``CASES`` по номеру строки) или ссылка на тест, где
она уже проверена (``ELSEWHERE``); тест покрытия падает, если строка таблицы осталась без
проверки.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.adm.helpers import step_up
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import World
from tests.integration.core.test_nodes_api import _create, _patch
from tests.security.stocked import Stocked, stocked
from tests.security.test_matrix_roles import _contract

from estimator.cli.seed_demo import _principal
from estimator.db.enums import ProjectStatus, SystemRole
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.services.customer_questions import flow

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-02"),
              pytest.mark.spec("SEC-AUTHZ-05")]  # fmt: skip

Check = Callable[[World, AsyncSession, Stocked], Awaitable[None]]
CASES: dict[int, Check] = {}
#: Строки, проверенные другими тестами.
ELSEWHERE = {
    22: "tests/integration/adm/test_ad_search_api.py::test_project_moderator_adds_from_ad",
    23: "tests/integration/adm/test_ad_search_api.py::test_project_moderator_adds_from_ad",
}


def case(*numbers: int) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        for n in numbers:
            CASES[n] = fn
        return fn

    return register


def _examples() -> list[dict[str, Any]]:
    return _contract()[0]["authz_examples"]


async def _version(db: AsyncSession, node: Any) -> int:
    row = await db.get(Node, uuid.UUID(str(node)), populate_existing=True)
    assert row is not None
    return row.version


async def _leaf_patch(actor: Any, db: AsyncSession, node: Any) -> int:
    return (await _patch(actor, node, await _version(db, node), r="13")).status_code


async def _frontend_leaf(db: AsyncSession, st: Stocked) -> str:
    branch = await st.s.branch(db, st.s.frontend)
    made = await _create(st.s.frontend_expert, st.s.pid, branch.id, title="Экран", o="1", r="2",
                         p="3")  # fmt: skip
    assert made.status_code == 201, made.text
    return made.json()["node"]["id"]


@case(1, 2)
async def _expert_own_and_foreign_branch(world: World, db: AsyncSession, st: Stocked) -> None:
    assert await _leaf_patch(st.s.backend_expert, db, st.ids["node"]) == 200
    assert await _leaf_patch(st.s.backend_expert, db, await _frontend_leaf(db, st)) == 403


@case(3)
async def _expert_moves_leaf_to_foreign_branch(world: World, db: AsyncSession, st: Stocked) -> None:
    frontend = await st.s.branch(db, st.s.frontend)
    node = st.ids["node"]
    moved = await st.s.backend_expert.post(f"/nodes/{node}/move", json={
        "base_version": await _version(db, node), "new_parent_id": str(frontend.id),
    })  # fmt: skip
    assert moved.status_code == 403, moved.text


@case(4, 5)
async def _expert_no_money_no_notes(world: World, db: AsyncSession, st: Stocked) -> None:
    for part in ("money", "notes"):
        assert (await st.s.backend_expert.get(f"/projects/{st.s.pid}/{part}")).status_code == 403


@case(6)
async def _stranger_expert_404(world: World, db: AsyncSession, st: Stocked) -> None:
    other = await stocked(world, db)
    assert (await other.s.backend_expert.get(f"/projects/{st.s.pid}/tree")).status_code == 404


@case(7)
async def _presale_cannot_estimate(world: World, db: AsyncSession, st: Stocked) -> None:
    assert await _leaf_patch(st.presale, db, st.ids["node"]) == 403


@case(8, 13, 14)
async def _outsiders_do_not_see_tree(world: World, db: AsyncSession, st: Stocked) -> None:
    for role in (SystemRole.ADMIN, SystemRole.SECURITY_AUDITOR, SystemRole.SUPERADMIN):
        got = await (await world.actor(role)).get(f"/projects/{st.s.pid}/tree")
        assert got.status_code == 404, (role, got.text)


@case(9, 10)
async def _support_session_reads_only(world: World, db: AsyncSession, st: Stocked) -> None:
    await set_setting(db, "security.admin_networks", [])
    admin = await world.actor(SystemRole.ADMIN)
    await step_up(world, admin)
    opened = await admin.post(f"/admin/projects/{st.s.pid}/support-session",
                              json={"reason": "Проверка жалобы на расчёт итогов"})  # fmt: skip
    assert opened.status_code == 201, opened.text
    assert (await admin.get(f"/projects/{st.s.pid}/money")).status_code == 403
    assert await _leaf_patch(admin, db, st.ids["node"]) == 403


@case(11, 12, 18)
async def _presale_head_reads_money_only(world: World, db: AsyncSession, st: Stocked) -> None:
    head = await world.actor(SystemRole.PRESALE_HEAD)
    assert (await head.get(f"/projects/{st.s.pid}/money")).status_code == 200
    assert await _leaf_patch(head, db, st.ids["node"]) == 403
    assert (await head.post(f"/projects/{st.s.pid}/notes", json={"body": "x"})).status_code == 403


@case(15)
async def _moderator_edits_any_branch(world: World, db: AsyncSession, st: Stocked) -> None:
    assert await _leaf_patch(st.s.moderator, db, st.ids["node"]) == 200
    assert await _leaf_patch(st.s.moderator, db, await _frontend_leaf(db, st)) == 200


@case(16)
async def _moderator_without_totp(world: World, db: AsyncSession, st: Stocked) -> None:
    await set_setting(db, "security.mfa_policy", {"moderator": "optional"})
    session = await world.session_for(st.s.moderator.id, SystemRole.MODERATOR, mfa=False)
    await set_setting(db, "security.mfa_policy", {"moderator": "required"})
    got = await session.get(f"/projects/{st.s.pid}/money")
    assert (got.status_code, got.json()["code"]) == (403, "TOTP_REQUIRED"), got.text


@case(17)
async def _presale_head_join_archived(world: World, db: AsyncSession, st: Stocked) -> None:
    project = await db.get(Project, st.s.pid)
    assert project is not None
    project.status = ProjectStatus.ARCHIVED
    await db.flush()
    head = await world.actor(SystemRole.PRESALE_HEAD)
    joined = await head.post(f"/projects/{st.s.pid}/join-as-moderator")
    assert (joined.status_code, joined.json()["code"]) == (409, "PROJECT_STATUS_CONFLICT")


@case(19)
async def _presale_head_cannot_add_moderator(world: World, db: AsyncSession, st: Stocked) -> None:
    head = await world.actor(SystemRole.PRESALE_HEAD)
    other = await world.actor(SystemRole.MODERATOR)
    team = (await st.s.moderator.get(f"/projects/{st.s.pid}/members")).json()["items"]
    members = [{"user_id": m["user"]["id"], "role": m["role"], "discipline_id": m["discipline_id"],
                "is_reviewer": m.get("is_reviewer", False)} for m in team]  # fmt: skip
    members.append({"user_id": str(other.id), "role": "moderator"})
    put = await head.put(f"/projects/{st.s.pid}/members", json={"members": members})
    assert put.status_code == 403, put.text


@case(20, 21)
async def _only_author_resolves_answered_cq(world: World, db: AsyncSession, st: Stocked) -> None:
    tid = st.ids["cq_thread"]
    await flow.mark_sent(db, _principal(st.presale.id, "presale", "Пресейл"), st.s.pid,
                         [uuid.UUID(str(tid))])  # fmt: skip
    answered = await st.presale.post(f"/threads/{tid}/answer", json={"body": "REST, JSON"})
    assert answered.status_code == 200, answered.text
    stranger = await st.reviewer.post(f"/threads/{tid}/resolve", json={})
    assert stranger.status_code == 403, stranger.text
    author = await st.s.backend_expert.post(f"/threads/{tid}/resolve", json={})
    assert author.status_code == 200, author.text


@pytest.mark.parametrize("check", sorted(set(CASES.values()), key=lambda f: min(
    n for n, g in CASES.items() if g is f)), ids=lambda f: f.__name__.strip("_"))  # fmt: skip
async def test_authz_example(world: World, db_session: AsyncSession, check: Check) -> None:
    st = await stocked(world, db_session)
    await check(world, db_session, st)


def test_every_example_has_a_check() -> None:
    rows = range(1, len(_examples()) + 1)
    missing = [n for n in rows if n not in CASES and n not in ELSEWHERE]
    assert missing == [], [_examples()[n - 1] for n in missing]
