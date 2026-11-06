"""Общие механизмы REST API v1 (API-003): ошибки RFC 9457, ``DecimalString``, курсорная пагинация,
роутер с обязательным правом, повторы по ``Idempotency-Key``."""

from estimator.api.common.decimal import DecimalString, format_decimal, parse_decimal
from estimator.api.common.errors import ApiError, install_error_handlers, new_error_id
from estimator.api.common.idempotency import Idempotency, IdempotencyGuard
from estimator.api.common.pagination import Page, PageParams, PageRequest
from estimator.api.common.router import ApiRouter

__all__ = [
    "ApiError",
    "ApiRouter",
    "DecimalString",
    "Idempotency",
    "IdempotencyGuard",
    "Page",
    "PageParams",
    "PageRequest",
    "format_decimal",
    "install_error_handlers",
    "new_error_id",
    "parse_decimal",
]
