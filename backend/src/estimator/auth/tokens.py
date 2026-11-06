"""Одноразовые токены ссылок активации и сброса пароля (AUTH-008; SEC-AUTH-03, FR-AUTH-LOC-01, 03).

Токен — 256 бит из ``secrets``, в ссылке ``?token=``; в ``auth_tokens`` хранится только SHA-256.
Новый токен того же вида аннулирует прежние (``revoked_at``). Использование — один раз:
строка блокируется ``FOR UPDATE``, проверяются срок, ``used_at`` и ``revoked_at``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import AuthTokenKind
from estimator.db.models.users import AuthToken

#: Срок ссылки: активация — 72 часа (FR-AUTH-LOC-01), сброс — 60 минут (FR-AUTH-LOC-03).
TTL: dict[AuthTokenKind, timedelta] = {
    AuthTokenKind.ACTIVATION: timedelta(hours=72),
    AuthTokenKind.PASSWORD_RESET: timedelta(minutes=60),
}
#: Путь страницы фронтенда для ссылки.
PAGES: dict[AuthTokenKind, str] = {
    AuthTokenKind.ACTIVATION: "/activate",
    AuthTokenKind.PASSWORD_RESET: "/password/reset",
}
MAX_TOKEN_LENGTH = 128


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii", "replace")).digest()


def link(base_url: str, kind: AuthTokenKind, token: str) -> str:
    return f"{base_url.rstrip('/')}{PAGES[kind]}?token={token}"


async def issue(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: AuthTokenKind,
    *,
    created_by: uuid.UUID | None = None,
    now: datetime | None = None,
) -> str:
    """Выпустить токен; прежние неиспользованные токены этого вида аннулируются."""
    now = now or datetime.now(UTC)
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.kind == kind,
            AuthToken.used_at.is_(None),
            AuthToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user_id,
            kind=kind,
            token_hash=token_hash(token),
            created_by=created_by,
            created_at=now,
            expires_at=now + TTL[kind],
        )
    )
    await db.flush()
    return token


async def find_valid(
    db: AsyncSession, token: str, kind: AuthTokenKind, *, now: datetime | None = None
) -> AuthToken | None:
    """Действующий токен (строка заблокирована до конца транзакции) или ``None``.

    Отметку об использовании ставит :func:`mark_used` — после того как действие удалось,
    чтобы отказ (например, слабый пароль) не сжигал ссылку.
    """
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    now = now or datetime.now(UTC)
    row = await db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == token_hash(token), AuthToken.kind == kind)
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.revoked_at is not None:
        return None
    if row.expires_at <= now:
        return None
    return row


async def mark_used(db: AsyncSession, row: AuthToken, *, now: datetime | None = None) -> None:
    row.used_at = now or datetime.now(UTC)
    await db.flush()


async def consume(
    db: AsyncSession, token: str, kind: AuthTokenKind, *, now: datetime | None = None
) -> AuthToken | None:
    """Найти и сразу использовать токен. ``None`` — не найден, истёк, использован, аннулирован."""
    row = await find_valid(db, token, kind, now=now)
    if row is not None:
        await mark_used(db, row, now=now)
    return row
