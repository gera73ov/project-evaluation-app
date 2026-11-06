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
AUTH). Для остальных кодов роутер вызывает авторизатор ``app.state.authorize(request, permission)``
— его ставит движок прав SEC-005. Пока авторизатора нет, такие операции отвечают 403 ``FORBIDDEN``
(закрыто по умолчанию).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.types import DecoratedCallable

from estimator.api.common.errors import ApiError

Permission = str | Sequence[str]
#: Псевдоправа contracts/api-conventions.md 4 п. 1 — проверяются зависимостями эндпоинта
SELF_CHECKED = frozenset({"public", "authenticated", "session.pre_mfa"})
Authorizer = Callable[[Request, tuple[str, ...]], Awaitable[None]]


def _normalize(permission: Permission | None) -> tuple[str, ...]:
    if permission is None:
        raise TypeError("операция ApiRouter должна объявить permission= (SEC-AUTHZ-02)")
    codes = (permission,) if isinstance(permission, str) else tuple(permission)
    if not codes or not all(isinstance(c, str) and c for c in codes):
        raise TypeError("permission — непустой код права или список кодов")
    return codes


def is_self_checked(codes: tuple[str, ...]) -> bool:
    return all(c in SELF_CHECKED or c.startswith("token.") for c in codes)


def permission_guard(codes: tuple[str, ...]) -> Callable[[Request], Awaitable[None]]:
    """Зависимость: проверка права через ``app.state.authorize`` (SEC-005)."""

    async def guard(request: Request) -> None:
        authorize: Authorizer | None = getattr(request.app.state, "authorize", None)
        if authorize is None:
            raise ApiError("FORBIDDEN")
        await authorize(request, codes)

    return guard


class ApiRouter(APIRouter):
    """``APIRouter`` с обязательным ``permission`` у каждой операции."""

    def add_api_route(  # type: ignore[override]
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        permission: Permission | None = None,
        **kwargs: Any,
    ) -> None:
        extra = dict(kwargs.pop("openapi_extra", None) or {})
        dependencies = list(kwargs.pop("dependencies", None) or [])
        if permission is None and "x-permission" in extra:
            # include_router вложенного ApiRouter: право и проверка уже в маршруте
            codes = _normalize(extra["x-permission"])
        else:
            codes = _normalize(permission)
            extra["x-permission"] = codes[0] if len(codes) == 1 else list(codes)
            if not is_self_checked(codes):
                dependencies.insert(0, Depends(permission_guard(codes)))
        super().add_api_route(
            path, endpoint, openapi_extra=extra, dependencies=dependencies, **kwargs
        )
        self.routes[-1].permission = codes  # type: ignore[attr-defined]

    def api_route(  # type: ignore[override]
        self, path: str, *, permission: Permission | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_api_route(path, func, permission=permission, **kwargs)
            return func

        return decorator

    def _method(self, method: str):  # type: ignore[no-untyped-def]
        def route(
            path: str, *, permission: Permission | None = None, **kwargs: Any
        ) -> Callable[[DecoratedCallable], DecoratedCallable]:
            _normalize(permission)  # ошибка — в строке объявления, а не при регистрации
            return self.api_route(path, permission=permission, methods=[method], **kwargs)

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
