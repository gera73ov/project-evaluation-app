"""TOTP и резервные коды (AUTH-006; FR-2FA-01, FR-2FA-04, SEC-CRYPT-03, SEC-AUTH-02, TC-AUTH-04).

* RFC 6238: шаг 30 с, 6 цифр, SHA-1 (совместимо с приложениями-аутентификаторами); допуск ±1 шаг.
* Защита от повтора: принятый шаг записывается в Redis ``totp:used:{user_id}:{step}`` (``SET NX``,
  TTL 120 с, DB-D02): тот же или более ранний код повторно не проходит, пока шаг в окне допуска.
* Секрет хранится зашифрованным (контекст ``users.totp_secret_enc:{user_id}``).
* 10 резервных кодов по 8 цифр; в ``backup_codes`` — только хэши Argon2id, код одноразовый.
* Все сравнения кодов — ``hmac.compare_digest``.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pyotp
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.users import BackupCode
from estimator.security.crypto import contexts
from estimator.security.crypto.aead import Cipher

ISSUER = "Оценка проектов"
STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # ±1 шаг
USED_TTL = 120
BACKUP_CODES = 10
BACKUP_DIGITS = 8

#: Хэш резервных кодов: Argon2id с умеренной памятью (минимум OWASP), чтобы 10 кодов
#: хэшировались и проверялись без всплеска памяти; перебор 10^8 кодов офлайн всё равно дорог.
BACKUP_HASHER = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1, type=Type.ID)


def new_secret() -> str:
    """Секрет Base32 (160 бит) — показывается пользователю и кодируется в QR."""
    return pyotp.random_base32(length=32)


def provisioning_uri(secret: str, login: str) -> str:
    """``otpauth://`` для QR-кода (FR-2FA-04)."""
    return pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS).provisioning_uri(
        name=login, issuer_name=ISSUER
    )


def encrypt_secret(cipher: Cipher, user_id: uuid.UUID, secret: str) -> bytes:
    return cipher.encrypt_text(secret, contexts.totp_secret(user_id))


def decrypt_secret(cipher: Cipher, user_id: uuid.UUID, blob: bytes) -> str:
    return cipher.decrypt_text(bytes(blob), contexts.totp_secret(user_id))


def is_code_format(code: str, digits: int = DIGITS) -> bool:
    return len(code) == digits and code.isascii() and code.isdigit()


class TotpVerifier:
    """Проверка кода с допуском ±1 шаг и защитой от повтора; ``clock`` — для тестов."""

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    def matching_step(self, secret: str, code: str) -> int | None:
        """Шаг, которому соответствует код, или ``None``. Проверяются все шаги окна."""
        if not is_code_format(code):
            return None
        totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)
        current = int(self._clock()) // STEP_SECONDS
        found = None
        for step in range(current - WINDOW, current + WINDOW + 1):
            expected = totp.generate_otp(step)
            if hmac.compare_digest(expected.encode(), code.encode()) and found is None:
                found = step
        return found

    async def verify(self, user_id: uuid.UUID | str, secret: str, code: str) -> bool:
        step = self.matching_step(secret, code)
        if step is None:
            return False
        # Принятый шаг и все более ранние шаги окна закрываются: код нельзя повторить,
        # и нельзя «откатиться» на код предыдущего шага после более нового.
        current = int(self._clock()) // STEP_SECONDS
        latest = await self._redis.get(f"totp:last:{user_id}")
        if latest is not None and step <= int(latest):
            return False
        claimed = await self._redis.set(f"totp:used:{user_id}:{step}", 1, nx=True, ex=USED_TTL)
        if not claimed:
            return False
        ttl = (current + WINDOW + 2 - step) * STEP_SECONDS
        await self._redis.set(f"totp:last:{user_id}", step, ex=max(ttl, USED_TTL))
        return True


# --- резервные коды ---


def generate_backup_codes() -> list[str]:
    return [
        f"{secrets.randbelow(10**BACKUP_DIGITS):0{BACKUP_DIGITS}d}" for _ in range(BACKUP_CODES)
    ]


def _backup_matches(code_hash: str, code: str) -> bool:
    try:
        return BACKUP_HASHER.verify(code_hash, code)
    except (VerificationError, InvalidHashError):
        return False


async def replace_backup_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Удалить старые коды и выдать 10 новых (показываются один раз)."""
    codes = generate_backup_codes()
    hashes = await asyncio.to_thread(lambda: [BACKUP_HASHER.hash(c) for c in codes])
    await session.execute(delete(BackupCode).where(BackupCode.user_id == user_id))
    session.add_all(BackupCode(user_id=user_id, code_hash=h) for h in hashes)
    await session.flush()
    return codes


async def consume_backup_code(session: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    """Принять неиспользованный резервный код и пометить его использованным."""
    if not is_code_format(code, BACKUP_DIGITS):
        return False
    rows = (
        await session.scalars(
            select(BackupCode)
            .where(BackupCode.user_id == user_id, BackupCode.used_at.is_(None))
            .with_for_update()
        )
    ).all()
    for row in rows:
        if await asyncio.to_thread(_backup_matches, row.code_hash, code):
            row.used_at = datetime.now(UTC)
            await session.flush()
            return True
    return False


async def remaining_backup_codes(session: AsyncSession, user_id: uuid.UUID) -> int:
    rows = await session.scalars(
        select(BackupCode.id).where(BackupCode.user_id == user_id, BackupCode.used_at.is_(None))
    )
    return len(rows.all())
