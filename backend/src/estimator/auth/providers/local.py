"""Провайдер ``local``: пароли приложения, Argon2id (AUTH-001; SEC-AUTH-01, FR-AUTH-LOC-*).

* Параметры Argon2id: память 64 МиБ, 3 итерации, параллелизм 2 — не ниже SEC-AUTH-01.
  Параметры записаны в строке хэша; хэш со старыми параметрами пересчитывается при входе.
* Неизвестный логин и учётка без пароля проверяются против фиктивного хэша, чтобы время
  ответа не выдавало существование логина.
* Статус проверяется **после** пароля: с неверным паролем заблокированный пользователь получает
  тот же ответ, что и любой другой.
* Хэширование — в пуле потоков: Argon2 занимает CPU и память и не должен держать цикл событий.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import ClassVar

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers.base import (
    LOCAL,
    AuthProvider,
    AuthResult,
    Credentials,
    Identity,
    register_provider,
)
from estimator.db.enums import UserSource, UserStatus
from estimator.db.models.users import User
from estimator.logging import get_logger

log = get_logger(__name__)

MEMORY_KIB = 64 * 1024
TIME_COST = 3
PARALLELISM = 2

HASHER = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_KIB,
    parallelism=PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Хэш не Argon2id или с параметрами слабее текущих."""
    try:
        return HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-constant-time")


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(verify_password, password_hash, password)


class LocalProvider(AuthProvider):
    name: ClassVar[str] = LOCAL

    async def authenticate(self, session: AsyncSession, credentials: Credentials) -> AuthResult:
        login = credentials.login.strip()
        user = await session.scalar(select(User).where(User.login == login))
        usable = (
            user is not None
            and user.source is UserSource.LOCAL
            and user.status is not UserStatus.ANONYMIZED
        )
        if user is None or not usable:
            await verify_password_async(_dummy_hash(), credentials.password)
            return AuthResult.failure("user_not_found")
        if user.password_hash is None:
            await verify_password_async(_dummy_hash(), credentials.password)
            reason = (
                "pending_password"
                if user.status is UserStatus.PENDING_PASSWORD
                else "wrong_password"
            )
            return AuthResult.failure(reason, user.id)
        if not await verify_password_async(user.password_hash, credentials.password):
            return AuthResult.failure("wrong_password", user.id)
        if user.status is UserStatus.BLOCKED:
            return AuthResult.failure("user_blocked", user.id)
        if user.status is UserStatus.PENDING_PASSWORD:
            return AuthResult.failure("pending_password", user.id)
        if needs_rehash(user.password_hash):
            user.password_hash = await hash_password_async(credentials.password)
            await session.flush()
            log.info("password_rehashed", user_id=str(user.id))
        return AuthResult.success(
            Identity(
                provider=LOCAL,
                external_id=str(user.id),
                login=user.login,
                attributes={"full_name": user.full_name, "email": user.email},
                user_id=user.id,
            )
        )


register_provider(LOCAL, LocalProvider)
