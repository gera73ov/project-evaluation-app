"""Проверка прав в FastAPI (SEC-005; SEC-AUTHZ-01…03).

* :func:`gate` — зависимость маршрута по ``x-permission`` (её ставит ``ApiRouter`` API-003 и
  можно ставить вручную): находит объект по параметру пути, проверяет право и кладёт
  :class:`~estimator.security.authz.engine.Access` в ``request.state.access``.
* :data:`AuthorizerDep` — для проверок внутри обработчика, когда объект известен только после
  загрузки (узел, сообщение, источник копирования).

Объект берётся из пути: ``/projects/{id}…`` — проект; для других объектов домен регистрирует
загрузчик :func:`register_resolver` (например, ``/nodes/{id}`` → проект и дисциплина узла).
Без загрузчика проверяются только глобальные выдачи — проектные права не дадут доступа
(запрещено по умолчанию). Роли и членство читаются из БД на каждом запросе.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Collection
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.auth.policy import read_settings
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.session import DbSession
from estimator.redis_client import get_redis
from estimator.security import audit
from estimator.security.authz.catalog import PSEUDO, Catalog, load_catalog
from estimator.security.authz.engine import (
    Access,
    AccessDenied,
    Membership,
    Subject,
    Target,
    decide_any,
)
from estimator.security.networks import address_allowed, load_admin_networks
from estimator.security.ratelimit.limiter import client_ip

API_PREFIX = "/api/v1"
PROJECT_PATH = "/projects/{id}"
DENIED_WINDOW = 60  # security.access_denied — не чаще раза в минуту на пользователя и объект
DENIED_KEY = "authz:denied:"
OPENED_KEY = "authz:ph_opened:"

Resolver = Callable[[AsyncSession, uuid.UUID], Awaitable[Target | None]]
_RESOLVERS: dict[str, Resolver] = {}


def register_resolver(path_prefix: str, resolver: Resolver) -> None:
    """Загрузчик объекта для путей ``{path_prefix}…`` с параметром ``{id}``."""
    if not path_prefix.endswith("/{id}"):
        raise ValueError("префикс должен оканчиваться на /{id}")
    _RESOLVERS[path_prefix] = resolver


async def project_target(db: AsyncSession, project_id: uuid.UUID) -> Target | None:
    status = await db.scalar(select(Project.status).where(Project.id == project_id))
    if status is None:
        return None
    return Target(project_id=project_id, project_status=str(status))


class Authorizer:
    """Проверки прав одного запроса."""

    def __init__(
        self,
        request: Request,
        principal: Principal,
        db: AsyncSession,
        redis: Redis,
        catalog: Catalog | None = None,
    ) -> None:
        self.request = request
        self.principal = principal
        self.db = db
        self.redis = redis
        self.catalog = catalog or load_catalog()

    @property
    def ip(self) -> str:
        return client_ip(self.request)

    async def _facts(self, codes: tuple[str, ...]) -> dict[str, str]:
        keys = self.catalog.required_settings(codes)
        if not keys:
            return {}
        values = await read_settings(self.db, *sorted(keys))
        return {k: str(v) for k, v in values.items()}

    async def subject(self, project_id: uuid.UUID | None, codes: tuple[str, ...]) -> Subject:
        memberships: tuple[Membership, ...] = ()
        if project_id is not None:
            rows = await self.db.execute(
                select(
                    ProjectMember.role, ProjectMember.discipline_id, ProjectMember.is_reviewer
                ).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == self.principal.user_id,
                )
            )
            memberships = tuple(Membership(str(r), d, bool(rv)) for r, d, rv in rows.all())
        network_ok = True
        if any(self.catalog.permission(c).network for c in codes):
            network_ok = address_allowed(self.ip, await load_admin_networks(self.db))
        p = self.principal
        return Subject(
            user_id=p.user_id,
            roles=frozenset(str(r) for r in p.roles),
            mfa_passed=p.mfa_passed,
            step_up_active=p.step_up_active(),
            network_allowed=network_ok,
            memberships=memberships,
            support=project_id is not None and p.in_support(project_id),
            facts=await self._facts(codes),
        )

    async def check(self, codes: str | Collection[str], target: Target | None = None) -> Access:
        """Проверить право (или любое из списка) на объекте; отказ — HTTPException."""
        wanted = (codes,) if isinstance(codes, str) else tuple(codes)
        target = target or Target()
        subject = await self.subject(target.project_id, wanted)
        try:
            access = decide_any(self.catalog, subject, wanted, target)
        except AccessDenied as exc:
            await self._audit_denied(exc, target)
            raise HTTPException(exc.status, detail=exc.detail()) from None
        if access.via_presale_head and target.project_id is not None:
            await self._audit_presale_head(target.project_id)
        return access

    async def project(self, project_id: uuid.UUID, codes: str | Collection[str]) -> Access:
        """Право на проекте по его идентификатору; нет проекта — 404."""
        target = await project_target(self.db, project_id)
        if target is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND"})
        return await self.check(codes, target)

    def _route(self) -> str:
        """Шаблон пути без значений (для аудита)."""
        route = self.request.scope.get("route")
        return str(getattr(route, "path", "")) or "?"

    async def _audit_denied(self, exc: AccessDenied, target: Target) -> None:
        p = self.principal
        common: dict[str, Any] = {
            "user_id": p.user_id,
            "login": p.login,
            "ip": self.ip,
            "session_id": p.session_id,
        }
        if exc.code == "NOT_FOUND" and self.catalog.permission(exc.permission).network:
            await audit.write_detached(
                self.db, "security.network_denied", "denied", **common,
                details={"route": self._route()},
            )  # fmt: skip
            return
        if target.project_id is None or exc.status not in (403, 404):
            return
        key = f"{DENIED_KEY}{p.user_id}:{target.project_id}:{exc.permission}"
        if not await self.redis.set(key, "1", nx=True, ex=DENIED_WINDOW):
            await self.redis.incr(key + ":n")
            await self.redis.expire(key + ":n", DENIED_WINDOW * 2)
            return
        suppressed = int(await self.redis.getdel(key + ":n") or 0)
        await audit.write_detached(
            self.db, "security.access_denied", "denied", **common,
            object_type="project", object_id=target.project_id, project_id=target.project_id,
            details={
                "status": exc.status, "permission": exc.permission,
                "method": getattr(self.request, "method", "WS"),  # WS: подписка RT-003
                "route": self._route(), "suppressed": suppressed,
            },
        )  # fmt: skip

    async def _audit_presale_head(self, project_id: uuid.UUID) -> None:
        """Первое за сессию открытие чужого проекта руководителем пресейла (R-PRESALE-HEAD)."""
        p = self.principal
        ttl = max(1, int(p.session.absolute_at - time.time()))
        key = f"{OPENED_KEY}{p.session_hash.hex()}:{project_id}"
        if not await self.redis.set(key, "1", nx=True, ex=ttl):
            return
        await audit.write(
            self.db,
            "project.opened_by_presale_head",
            user_id=p.user_id,
            login=p.login,
            ip=self.ip,
            session_id=p.session_id,
            object_type="project",
            object_id=project_id,
            project_id=project_id,
        )


def get_authorizer(
    request: Request,
    principal: ActivePrincipal,
    db: DbSession,
    redis: Annotated[Redis, Depends(get_redis)],
) -> Authorizer:
    return Authorizer(request, principal, db, redis)


AuthorizerDep = Annotated[Authorizer, Depends(get_authorizer)]


def _object_path(request: Request) -> tuple[str, uuid.UUID] | None:
    """Шаблон объекта (``/projects/{id}``, зарегистрированный префикс) и его идентификатор.

    Сравнивается фактический путь запроса, а не шаблон маршрута: так результат не зависит
    от того, с каким префиксом подключён роутер.
    """
    raw = request.path_params.get("id")
    if raw is None:
        # ``/me/view-state/{project_id}`` (CORE-027): объект — проект из параметра project_id
        project = request.path_params.get("project_id")
        if project is None:
            return None
        try:
            return PROJECT_PATH, uuid.UUID(str(project))
        except ValueError:
            raise HTTPException(404, detail={"code": "NOT_FOUND"}) from None
    path = request.url.path.removeprefix(API_PREFIX)
    for template in (PROJECT_PATH, *_RESOLVERS):
        if path.startswith(template.replace("{id}", str(raw))):
            try:
                return template, uuid.UUID(str(raw))
            except ValueError:
                raise HTTPException(404, detail={"code": "NOT_FOUND"}) from None
    return None


async def target_from_path(request: Request, db: AsyncSession) -> Target:
    """Объект запроса по пути; без объекта — системный (только глобальные выдачи)."""
    found = _object_path(request)
    if found is None:
        return Target()
    template, object_id = found
    if template == PROJECT_PATH:
        target = await project_target(db, object_id)
    else:
        target = await _RESOLVERS[template](db, object_id)
    if target is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return target


def gate(codes: str | Collection[str]) -> Any:
    """``Depends`` для маршрута с правом ``codes`` («любое из»). Псевдоправа сюда не передают."""
    wanted = (codes,) if isinstance(codes, str) else tuple(codes)
    if not wanted:
        raise ValueError("gate без прав")
    catalog = load_catalog()
    for code in wanted:
        if code in PSEUDO:
            raise ValueError(f"псевдоправо {code!r} проверяют зависимости AUTH")
        catalog.permission(code)

    async def check_permission(request: Request, authz: AuthorizerDep) -> Access:
        target = await target_from_path(request, authz.db)
        access = await authz.check(wanted, target)
        request.state.access = access
        return access

    check_permission.authz_codes = wanted  # type: ignore[attr-defined]
    return Depends(check_permission)


#: Синоним для обработчиков: ``access: Annotated[Access, require("tree.read")]``.
require = gate
