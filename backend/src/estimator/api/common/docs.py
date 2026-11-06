"""Документация OpenAPI только на стендах (API-005; SPEC 15.1).

``/api/docs`` (Swagger UI) и ``/api/openapi.json`` есть только при ``APP_ENV`` из
:data:`DOCS_ENVS`. На ``prod`` маршрутов нет совсем — ответ 404 ``NOT_FOUND``, как на любой
неизвестный путь. Источник правды для клиентов — ``contracts/openapi.yaml``; сгенерированный
документ нужен для отладки и сверки реализации с контрактом (API-004).
"""

from __future__ import annotations

from typing import TypedDict

from estimator.config import AppEnv, Settings

DOCS_URL = "/api/docs"
OPENAPI_URL = "/api/openapi.json"
#: Окружения, где документация открыта
DOCS_ENVS = frozenset({AppEnv.DEV, AppEnv.TEST, AppEnv.STAGE})


class DocsUrls(TypedDict):
    docs_url: str | None
    redoc_url: None
    openapi_url: str | None


def docs_enabled(settings: Settings) -> bool:
    return settings.app_env in DOCS_ENVS


def docs_urls(settings: Settings) -> DocsUrls:
    """Аргументы ``FastAPI(...)``: адреса документации или ``None``, если она выключена."""
    enabled = docs_enabled(settings)
    return DocsUrls(
        docs_url=DOCS_URL if enabled else None,
        redoc_url=None,
        openapi_url=OPENAPI_URL if enabled else None,
    )
