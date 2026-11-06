"""Авторизация (SEC-005): каталог прав, движок решений и зависимости FastAPI.

``gate(codes)`` использует ``ApiRouter`` (API-003) для каждого маршрута с правом не из
псевдоправ; :func:`~estimator.security.authz.routes.assert_routes_protected` не даёт
приложению стартовать с незащищённым маршрутом (TC-SEC-01).
"""

from estimator.security.authz.deps import (
    Authorizer,
    AuthorizerDep,
    gate,
    register_resolver,
    require,
)
from estimator.security.authz.engine import Access, AccessDenied, Target

__all__ = [
    "Access",
    "AccessDenied",
    "Authorizer",
    "AuthorizerDep",
    "Target",
    "gate",
    "register_resolver",
    "require",
]
