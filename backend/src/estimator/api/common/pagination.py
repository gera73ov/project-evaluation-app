"""Курсорная пагинация (API-003; contracts/api-conventions.md 6, SPEC 15.1).

Курсор — base64url от JSON-позиции и HMAC-SHA256 (16 байт) по ней с привязкой к имени списка.
Подделанный, обрезанный или чужой курсор → 400 ``CURSOR_INVALID``; ``limit`` вне 1–200 — тоже
``CURSOR_INVALID`` (errors.yaml). Ключ HMAC выводится из мастер-ключа шифрования (SEC-CRYPT-01); без
него (dev) — случайный ключ процесса: курсоры не переживают перезапуск, клиент перезапрашивает
первую страницу.

Пример эндпоинта::

    @router.get("/projects", permission="project.read")
    async def list_projects(page: PageParams) -> Page[ProjectOut]:
        after = page.position("projects")            # None или {"id": "..."}
        rows = ...  # limit + 1 строк после after
        return Page.build(rows, page, "projects", lambda r: {"id": str(r.id)})
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel

from estimator.api.common.errors import ApiError
from estimator.config import get_settings

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_TAG_BYTES = 16


@lru_cache
def _cursor_key() -> bytes:
    raw = get_settings().encryption_key
    if raw is None:
        return secrets.token_bytes(32)
    from estimator.security.crypto.keys import parse_key

    master = parse_key(raw.get_secret_value()).key
    return hmac.new(master, b"estimator.api.cursor.v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encode_cursor(scope: str, position: dict[str, Any], key: bytes | None = None) -> str:
    """Подписать позицию списка ``scope``."""
    payload = json.dumps(position, separators=(",", ":"), sort_keys=True).encode()
    tag = hmac.new(key or _cursor_key(), scope.encode() + b"\0" + payload, hashlib.sha256)
    return _b64(tag.digest()[:_TAG_BYTES] + payload)


def decode_cursor(scope: str, cursor: str, key: bytes | None = None) -> dict[str, Any]:
    """Проверить подпись и вернуть позицию; иначе :class:`ApiError` ``CURSOR_INVALID``."""
    try:
        blob = _unb64(cursor)
        tag, payload = blob[:_TAG_BYTES], blob[_TAG_BYTES:]
        expected = hmac.new(
            key or _cursor_key(), scope.encode() + b"\0" + payload, hashlib.sha256
        ).digest()[:_TAG_BYTES]
        if len(tag) != _TAG_BYTES or not hmac.compare_digest(tag, expected):
            raise ValueError("подпись")
        position = json.loads(payload)
        if not isinstance(position, dict):
            raise ValueError("позиция")
    except (ValueError, TypeError) as exc:
        raise ApiError("CURSOR_INVALID") from exc
    return position


@dataclass(frozen=True)
class PageRequest:
    cursor: str | None
    limit: int

    def position(self, scope: str) -> dict[str, Any] | None:
        return decode_cursor(scope, self.cursor) if self.cursor else None


def page_params(
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query()] = DEFAULT_LIMIT,
) -> PageRequest:
    if not 1 <= limit <= MAX_LIMIT:
        raise ApiError("CURSOR_INVALID", detail=f"limit должен быть от 1 до {MAX_LIMIT}")
    return PageRequest(cursor=cursor, limit=limit)


PageParams = Annotated[PageRequest, Depends(page_params)]


class Page[T](BaseModel):
    """Ответ списка: ``{"items": [...], "next_cursor": "..." | null}``."""

    items: list[T]
    next_cursor: str | None

    @classmethod
    def build(
        cls,
        rows: Sequence[T],
        page: PageRequest,
        scope: str,
        position_of: Callable[[T], dict[str, Any]],
    ) -> Page[T]:
        """``rows`` — до ``limit + 1`` строк; лишняя строка значит «есть следующая страница»."""
        items = list(rows[: page.limit])
        more = len(rows) > page.limit
        next_cursor = encode_cursor(scope, position_of(items[-1])) if more and items else None
        return cls(items=items, next_cursor=next_cursor)
