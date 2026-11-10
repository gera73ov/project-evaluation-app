"""Роутер, который требует объявить право у каждой операции (API-003; SEC-AUTHZ-02).

::

    router = ApiRouter(prefix="/projects", tags=["Проекты"])

    @router.get("/{project_id}", permission="project.read")
    async def get_project(...): ...

    @router.post("/auth/login", permission="public")
    async def login(...): ...

Без ``permission`` объявление маршрута падает при импорте модуля (``TypeError``), так что операция
без права не доедет даже до тестов. Право попадает в OpenAPI как ``x-permission`` (его сверяет
API-004 с contracts/openapi.yaml) и в атрибут маршрута ``route.permission``.

Проверка права. Псевдоправа ``public``, ``token.*``, ``authenticated``, ``session.pre_mfa`` роутер
не проверяет: их проверяют зависимости эндпоинта (``current_principal`` и токены шага входа, трек
AUTH). Для остальных кодов роутер добавляет первой зависимостью
``estimator.security.authz.gate(codes)`` движка прав SEC-005. Маршрут без обеспеченного права не
даст приложению стартовать (``assert_routes_protected``, TC-SEC-01).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import APIRouter
from fastapi.types import DecoratedCallable

from estimator.security.authz import gate

Permission = str | Sequence[str]
#: Псевдоправа contracts/api-conventions.md 4 п. 1 — проверяются зависимостями эндпоинта
SELF_CHECKED = frozenset({"public", "authenticated", "session.pre_mfa"})


def _normalize(permission: Permission | None) -> tuple[str, ...]:
    if permission is None:
        raise TypeError("операция ApiRouter должна объявить permission= (SEC-AUTHZ-02)")
    codes = (permission,) if isinstance(permission, str) else tuple(permission)
    if not codes or not all(isinstance(c, str) and c for c in codes):
        raise TypeError("permission — непустой код права или список кодов")
    return codes


def is_self_checked(codes: tuple[str, ...]) -> bool:
    return all(c in SELF_CHECKED or c.startswith("token.") for c in codes)


def needs_step_up(codes: tuple[str, ...]) -> bool:
    """У права есть флаг ``step_up`` (contracts/permissions.yaml, R-STEP-UP)."""
    from estimator.security.authz.catalog import PSEUDO, load_catalog

    catalog = load_catalog()
    return any(catalog.permission(c).step_up for c in codes if c not in PSEUDO)


def permission_guard(codes: tuple[str, ...], *, step_up: bool = True) -> Any:
    """Зависимость проверки права: :func:`estimator.security.authz.gate` движка прав SEC-005.

    ``gate`` сам берёт принципала, сессию БД и Redis через ``Depends`` (FastAPI переиспользует их с
    эндпоинтом), проект — из параметра пути, и бросает ``HTTPException`` с ``detail={"code": ...}``.
    """
    return gate(codes, step_up=step_up)


class ApiRouter(APIRouter):
    """``APIRouter`` с обязательным ``permission`` у каждой операции."""

    def add_api_route(  # type: ignore[override]
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        permission: Permission | None = None,
        step_up: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """``step_up=False`` — операция без ``x-step-up``, хотя у права есть флаг ``step_up``
        (список, проверка без записи). По умолчанию step-up требует флаг права."""
        extra = dict(kwargs.pop("openapi_extra", None) or {})
        dependencies = list(kwargs.pop("dependencies", None) or [])
        if permission is None and "x-permission" in extra:
            # include_router вложенного ApiRouter: право и проверка уже в маршруте
            codes = _normalize(extra["x-permission"])
        else:
            codes = _normalize(permission)
            # форма как в контракте: строка или список (в т. ч. из одного кода)
            extra["x-permission"] = permission if isinstance(permission, str) else list(codes)
            required = needs_step_up(codes) and step_up is not False
            if step_up and not needs_step_up(codes):
                raise TypeError("step_up=True у операции, право которой step-up не требует")
            if required:
                extra["x-step-up"] = True
            if not is_self_checked(codes):
                dependencies.insert(0, permission_guard(codes, step_up=required))
        super().add_api_route(
            path, endpoint, openapi_extra=extra, dependencies=dependencies, **kwargs
        )
        self.routes[-1].permission = codes  # type: ignore[attr-defined]

    def api_route(  # type: ignore[override]
        self,
        path: str,
        *,
        permission: Permission | None = None,
        step_up: bool | None = None,
        **kwargs: Any,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_api_route(path, func, permission=permission, step_up=step_up, **kwargs)
            return func

        return decorator

    def _method(self, method: str):  # type: ignore[no-untyped-def]
        def route(
            path: str,
            *,
            permission: Permission | None = None,
            step_up: bool | None = None,
            **kwargs: Any,
        ) -> Callable[[DecoratedCallable], DecoratedCallable]:
            _normalize(permission)  # ошибка — в строке объявления, а не при регистрации
            return self.api_route(
                path, permission=permission, step_up=step_up, methods=[method], **kwargs
            )

        return route

    def get(self, path: str, **kwargs: Any):  # type: ignore[override,no-untyped-def]
        return self._method("GET")(path, **kwargs)

    def post(self, path: str, **kwargs: Any):  # type: ignore[override,no-untyped-def]
        return self._method("POST")(path, **kwargs)

    def put(self, path: str, **kwargs: Any):  # type: ignore[override,no-untyped-def]
        return self._method("PUT")(path, **kwargs)

    def patch(self, path: str, **kwargs: Any):  # type: ignore[override,no-untyped-def]
        return self._method("PATCH")(path, **kwargs)

    def delete(self, path: str, **kwargs: Any):  # type: ignore[override,no-untyped-def]
        return self._method("DELETE")(path, **kwargs)
