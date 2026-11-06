"""Ошибки API в формате RFC 9457 (API-003; contracts/api-conventions.md 5, SEC-WEB-09).

Как бросать ошибку из кода эндпоинта или сервиса::

    raise ApiError("FIELD_CONFLICT", detail="Поле r изменено", conflicts=[...], current_version=9)

Совместимый вариант (им пользуются ранние модули ``auth``/``security``)::

    raise HTTPException(429, detail={"code": "RATE_LIMITED", "retry_after": 30},
                        headers={"Retry-After": "30"})

Обработчики :func:`install_error_handlers` превращают оба вида в ``application/problem+json``:
``type``, ``title`` и ``status`` берутся из каталога по ``code``, расширения — только объявленные в
errors.yaml (лишние ключи отбрасываются с предупреждением в лог, чтобы в ответ не утекло то, что
контракт не разрешает, — FR-AUTH-AD-13). У каждого ответа есть ``error_id`` (ULID): он же пишется в
лог. Ответ 5xx не содержит ``detail`` и трассировки.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from estimator.api.common.catalog import CATALOG, TYPE_BASE
from estimator.logging import get_logger

log = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: Статусы Starlette без кода в теле → код каталога
_STATUS_CODES = {
    400: "MALFORMED_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}
#: Причины pydantic → машинная причина ``errors[].code`` (errors.yaml VALIDATION_FAILED)
_REASONS = {
    "missing": "required",
    "string_too_long": "too_long",
    "too_long": "too_long",
    "string_too_short": "too_short",
    "too_short": "too_short",
    "string_pattern_mismatch": "pattern",
    "enum": "enum",
    "literal_error": "enum",
    "extra_forbidden": "unknown_field",
}


def new_error_id() -> str:
    """ULID: 48 бит времени в мс и 80 случайных бит, 26 символов Crockford base32."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


class ApiError(Exception):
    """Ошибка с кодом из errors.yaml; ``extensions`` — поля тела сверх стандартных."""

    def __init__(
        self,
        code: str,
        *,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        if code not in CATALOG:
            raise ValueError(f"код {code!r} отсутствует в contracts/errors.yaml")
        super().__init__(code)
        self.code = code
        self.status = CATALOG[code].status
        self.detail = detail
        self.headers = dict(headers or {})
        self.extensions = extensions


def problem_body(
    code: str,
    *,
    error_id: str,
    detail: str | None = None,
    instance: str | None = None,
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Тело Problem Details по коду каталога (api-conventions.md 5 п. 2)."""
    spec = CATALOG[code]
    body: dict[str, Any] = {
        "type": TYPE_BASE + spec.type,
        "title": spec.title,
        "status": spec.status,
        "code": code,
        "error_id": error_id,
    }
    if detail and spec.status < 500:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    if spec.status < 500:
        for key, value in (extensions or {}).items():
            if key in spec.extensions:
                body[key] = value
            else:
                log.warning("problem_extension_dropped", code=code, key=key)
    return body


def problem_response(
    request: Request,
    code: str,
    *,
    detail: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error_id = new_error_id()
    status = CATALOG[code].status
    emit = log.error if status >= 500 else log.info
    emit("api_error", code=code, status=status, error_id=error_id, path=request.url.path)
    body = problem_body(
        code,
        error_id=error_id,
        detail=detail,
        instance=request.url.path,
        extensions=extensions,
    )
    return JSONResponse(
        body, status_code=status, headers=dict(headers or {}), media_type=PROBLEM_JSON
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(ApiError, exc)  # обработчик зарегистрирован на этот тип
    return problem_response(
        request, exc.code, detail=exc.detail, extensions=exc.extensions, headers=exc.headers
    )


async def _http_exception(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)  # обработчик зарегистрирован на этот тип
    payload = exc.detail
    code: str | None = None
    detail: str | None = None
    extensions: dict[str, Any] = {}
    if isinstance(payload, Mapping) and payload.get("code") in CATALOG:
        extensions = {k: v for k, v in payload.items() if k not in ("code", "detail")}
        code = str(payload["code"])
        detail = payload.get("detail")
    else:
        code = _STATUS_CODES.get(exc.status_code)
        if code is None:
            code = "INTERNAL_ERROR" if exc.status_code >= 500 else "MALFORMED_REQUEST"
    return problem_response(
        request, code, detail=detail, extensions=extensions, headers=getattr(exc, "headers", None)
    )


def _pointer(loc: tuple[Any, ...]) -> str:
    parts = list(loc[1:]) if loc and loc[0] == "body" else list(loc)
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)  # обработчик зарегистрирован на этот тип
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return problem_response(request, "MALFORMED_REQUEST")
    items = [
        {
            "field": _pointer(tuple(e.get("loc", ()))),
            "code": _REASONS.get(str(e.get("type")), "type"),
            "message": str(e.get("msg", "")),
        }
        for e in errors
    ]
    return problem_response(request, "VALIDATION_FAILED", extensions={"errors": items})


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    error_id = new_error_id()
    # Трассировка — только в лог; клиенту — error_id (SEC-WEB-09)
    log.error("unhandled_exception", error_id=error_id, path=request.url.path, exc_info=exc)
    body = problem_body("INTERNAL_ERROR", error_id=error_id, instance=request.url.path)
    return JSONResponse(body, status_code=HTTPStatus.INTERNAL_SERVER_ERROR, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:
    """Подключить обработчики RFC 9457 к приложению."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
