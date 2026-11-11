"""SEC-005: проверка прав в запросе — членство из БД, 404/403/409, TOTP, сети, аудит отказов.

SPEC SEC-AUTHZ-01…03, SEC-AUTHZ-05, FR-2FA-05, FR-PORT-01, FR-SA-06, TC-SEC-02.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import get_session_service
from estimator.auth.policy import SessionPolicy
from estimator.auth.sessions import COOKIE_NAME, SessionService
from estimator.db.enums import ProjectRole, ProjectStatus, SystemRole
from estimator.db.models.dictionaries import Discipline
from estimator.db.models.projects import Project, ProjectMember, SupportSession
from estimator.db.session import db_session as db_session_dependency
from estimator.redis_client import get_redis
from estimator.security.authz import Access, AuthorizerDep, Target, gate
from estimator.security.authz import deps as authz_deps
from estimator.security.authz.routes import assert_routes_protected
from estimator.security.web.csrf import CSRF_HEADER
from tests.integration.auth.conftest import Clock, complete_setup, set_setting
from tests.integration.auth.helpers import make_user
from tests.integration.db.conftest import as_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.spec("SEC-AUTHZ-01"),
    pytest.mark.spec("SEC-AUTHZ-03"),
]

NODES: dict[uuid.UUID, Target] = {}


async def _node(_db: AsyncSession, node_id: uuid.UUID) -> Target | None:
    return NODES.get(node_id)


def _body(access: Access) -> dict[str, Any]:
    return {
        "context": access.context,
        "sources": sorted(access.sources),
        "restricted": sorted(access.restricted),
        "money": access.money,
    }


def _router() -> APIRouter:
    router = APIRouter()

    @router.get("/projects/{id}/tree", openapi_extra={"x-permission": "tree.read"})
    async def tree(access: Annotated[Access, gate("tree.read")]) -> dict[str, Any]:
        return _body(access)

    @router.get("/projects/{id}/money", openapi_extra={"x-permission": "money.read"},
                dependencies=[gate("money.read")])  # fmt: skip
    async def money() -> dict[str, str]:
        return {"rate": "3000"}

    @router.patch("/nodes/{id}", openapi_extra={"x-permission": "tree.write"})
    async def patch_node(access: Annotated[Access, gate("tree.write")]) -> dict[str, Any]:
        return _body(access)

    @router.get("/system/health", openapi_extra={"x-permission": "system.health.read"},
                dependencies=[gate("system.health.read")])  # fmt: skip
    async def system_health() -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/admin/users", openapi_extra={"x-permission": "users.read"},
                dependencies=[gate("users.read")])  # fmt: skip
    async def users() -> list[str]:
        return []

    @router.get("/projects/{id}/source/{source}",
                openapi_extra={"x-permission": "branch.copy_from"},
                dependencies=[gate("branch.copy_from")])  # fmt: skip
    async def copy_source(source: uuid.UUID, authz: AuthorizerDep) -> dict[str, Any]:
        access = await authz.project(source, "project.read")
        return _body(access)

    @router.get("/projects/{id}/ad-search", openapi_extra={"x-permission": "project.ad_search"},
                dependencies=[gate("project.ad_search")])  # fmt: skip
    async def ad_search() -> list[str]:
        return []

    @router.get("/admin/users/{id}", openapi_extra={"x-permission": "users.read"},
                dependencies=[gate("users.read")])  # fmt: skip
    async def user_card(id: uuid.UUID) -> dict[str, str]:  # noqa: A002 — имя из пути
        return {"id": str(id)}

    return router


@pytest.fixture
async def client(
    db_session: AsyncSession, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    await as_app(db_session)
    await complete_setup(db_session)
    # тестовый загрузчик узла — только на время теста: иначе он подменяет боевой в процессе
    # и ломает права на узлы в тестах, которые идут следом в том же процессе
    monkeypatch.setitem(authz_deps._RESOLVERS, "/nodes/{id}", _node)
    app = FastAPI()
    app.include_router(_router(), prefix="/api/v1")
    assert_routes_protected(app)

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    service = SessionService(redis_client, Clock())
    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[get_session_service] = lambda: service
    app.dependency_overrides[get_redis] = lambda: redis_client
    transport = httpx.ASGITransport(app=app, client=("10.1.2.3", 1))
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        c.service = service  # type: ignore[attr-defined]
        yield c
    authz_deps._RESOLVERS.pop("/nodes/{id}", None)


class World:
    def __init__(self, db: AsyncSession, client: httpx.AsyncClient) -> None:
        self.db = db
        self.client = client
        self.csrf = ""

    async def project(self, status: ProjectStatus = ProjectStatus.ESTIMATION) -> Project:
        project = Project(name="Портал дилеров", customer="ООО Ромашка",
                          pm_percent=Decimal(18), status=status)  # fmt: skip
        self.db.add(project)
        await self.db.flush()
        return project

    async def discipline(self, name: str) -> uuid.UUID:
        return (await self.db.scalars(select(Discipline.id).where(Discipline.name == name))).one()

    async def user(
        self,
        *roles: SystemRole,
        member: tuple[Project, ProjectRole, uuid.UUID | None] | None = None,
        mfa: bool = True,
    ) -> uuid.UUID:
        user = await make_user(self.db, *roles)
        if member is not None:
            project, role, discipline = member
            self.db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role,
                                      discipline_id=discipline))  # fmt: skip
            await self.db.flush()
        service: SessionService = self.client.service  # type: ignore[attr-defined]
        sid, record = await service.create(
            self.db, user.id, roles, SessionPolicy(), ip="10.1.2.3", mfa_passed=mfa
        )
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE_NAME, sid)
        self.csrf = record.csrf
        return user.id

    async def get(self, path: str) -> httpx.Response:
        return await self.client.get(f"/api/v1{path}")

    async def patch(self, path: str) -> httpx.Response:
        return await self.client.patch(f"/api/v1{path}", headers={CSRF_HEADER: self.csrf})


@pytest.fixture
def world(db_session: AsyncSession, client: httpx.AsyncClient) -> World:
    return World(db_session, client)


async def _audit(db: AsyncSession, event: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text("SELECT details FROM audit.audit_log WHERE event_type = :e ORDER BY id"),
        {"e": event},
    )
    return [r[0] for r in rows.all()]


def _code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


@pytest.mark.spec("SEC-AUTHZ-05")
async def test_member_roles_come_from_db(world: World, db_session: AsyncSession) -> None:
    project = await world.project()
    backend = await world.discipline("Бэкенд")
    frontend = await world.discipline("Фронтенд")
    NODES[node_b := uuid.uuid4()] = Target(project.id, "estimation", frozenset({backend}))
    NODES[node_f := uuid.uuid4()] = Target(project.id, "estimation", frozenset({frontend}))

    await world.user(member=(project, ProjectRole.EXPERT, backend))
    tree = await world.get(f"/projects/{project.id}/tree")
    assert tree.status_code == 200
    assert tree.json() == {"context": "member", "sources": ["expert"], "restricted": [],
                           "money": False}  # fmt: skip
    assert (await world.patch(f"/nodes/{node_b}")).status_code == 200
    denied = await world.patch(f"/nodes/{node_f}")
    assert denied.status_code == 403
    assert denied.json()["detail"] == {"code": "FORBIDDEN", "permission": "tree.write"}
    assert (await world.get(f"/projects/{project.id}/money")).status_code == 403
    assert (await world.patch(f"/nodes/{uuid.uuid4()}")).status_code == 404

    project.status = ProjectStatus.COMPLETED
    NODES[node_b] = Target(project.id, "completed", frozenset({backend}))
    await db_session.flush()
    conflict = await world.patch(f"/nodes/{node_b}")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"code": "PROJECT_STATUS_CONFLICT",
                                         "project_status": "completed"}  # fmt: skip


@pytest.mark.spec("SEC-AUTHZ-03")
async def test_foreign_project_is_404_and_audited(world: World, db_session: AsyncSession) -> None:
    project = await world.project()
    other = await world.project()
    await world.user(member=(other, ProjectRole.MODERATOR, None))
    for _ in range(3):
        response = await world.get(f"/projects/{project.id}/tree")
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "NOT_FOUND"}
    assert (await world.get(f"/projects/{uuid.uuid4()}/tree")).status_code == 404
    assert (await world.get("/projects/not-a-uuid/tree")).status_code == 404
    rows = await _audit(db_session, "security.access_denied")
    assert len(rows) == 1  # повторы в течение минуты свёрнуты
    assert rows[0]["status"] == 404
    assert rows[0]["permission"] == "tree.read"
    assert rows[0]["route"] == "/projects/{id}/tree"
    assert rows[0]["suppressed"] == 0


@pytest.mark.spec("FR-2FA-05")
async def test_money_needs_totp(world: World) -> None:
    project = await world.project()
    await world.user(SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None),
                     mfa=False)  # fmt: skip
    response = await world.get(f"/projects/{project.id}/money")
    assert (response.status_code, _code(response)) == (403, "TOTP_REQUIRED")
    assert (await world.get(f"/projects/{project.id}/tree")).json()["money"] is False
    await world.user(SystemRole.MODERATOR, member=(project, ProjectRole.MODERATOR, None))
    assert (await world.get(f"/projects/{project.id}/money")).json() == {"rate": "3000"}
    assert (await world.get(f"/projects/{project.id}/tree")).json()["money"] is True


@pytest.mark.spec("FR-PORT-01")
async def test_presale_head_opening_is_audited_once(world: World, db_session: AsyncSession) -> None:
    project = await world.project(ProjectStatus.PREPARATION)
    await world.user(SystemRole.PRESALE_HEAD)
    for _ in range(2):
        response = await world.get(f"/projects/{project.id}/tree")
        assert response.json()["context"] == "any_project"
    assert (await world.get(f"/projects/{project.id}/money")).status_code == 200
    assert len(await _audit(db_session, "project.opened_by_presale_head")) == 1


@pytest.mark.spec("FR-ADM-06")
async def test_support_session_reads_without_money(world: World, db_session: AsyncSession) -> None:
    project = await world.project()
    admin = await world.user(SystemRole.ADMIN)
    assert (await world.get(f"/projects/{project.id}/tree")).status_code == 404
    db_session.add(SupportSession(admin_id=admin, project_id=project.id, reason="Разбор обращения",
                                  expires_at=await _in_minutes(db_session, 30)))  # fmt: skip
    await db_session.flush()
    tree = await world.get(f"/projects/{project.id}/tree")
    assert tree.json()["context"] == "support_session"
    assert (await world.get(f"/projects/{project.id}/money")).status_code == 403
    assert (await world.get("/admin/users")).status_code == 200


async def _in_minutes(db: AsyncSession, minutes: int) -> Any:
    return await db.scalar(text(f"SELECT now() + interval '{int(minutes)} minutes'"))


@pytest.mark.spec("FR-SA-06")
async def test_admin_networks(world: World, db_session: AsyncSession) -> None:
    await world.user(SystemRole.SUPERADMIN)
    assert (await world.get("/system/health")).status_code == 200
    await set_setting(db_session, "security.admin_networks", ["192.168.0.0/16"])
    response = await world.get("/system/health")
    assert (response.status_code, _code(response)) == (404, "NOT_FOUND")
    assert await _audit(db_session, "security.network_denied") == [{"route": "/system/health"}]
    await set_setting(db_session, "security.admin_networks", ["10.0.0.0/8"])
    assert (await world.get("/system/health")).status_code == 200


async def test_global_permission_and_object_check_in_handler(world: World) -> None:
    project = await world.project()
    source = await world.project(ProjectStatus.ARCHIVED)
    await world.user(member=(project, ProjectRole.MODERATOR, None))
    assert (await world.get("/admin/users")).status_code == 403
    response = await world.get(f"/projects/{project.id}/source/{source.id}")
    assert response.status_code == 404  # в источнике не участник
    response = await world.get(f"/projects/{project.id}/source/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.spec("FR-AUTH-AD-10")
async def test_setting_dependent_permission(world: World, db_session: AsyncSession) -> None:
    project = await world.project()
    await world.user(member=(project, ProjectRole.MODERATOR, None))
    assert (await world.get(f"/projects/{project.id}/ad-search")).status_code == 403
    await set_setting(db_session, "auth.mode", "ad")
    assert (await world.get(f"/projects/{project.id}/ad-search")).status_code == 200


async def test_id_outside_object_templates_is_global(world: World) -> None:
    await world.user(SystemRole.ADMIN)
    user_id = uuid.uuid4()
    assert (await world.get(f"/admin/users/{user_id}")).json() == {"id": str(user_id)}
