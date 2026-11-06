"""Общие помощники интеграционных тестов AUTH."""

from __future__ import annotations

import uuid
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.providers.local import hash_password
from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.users import User, UserRole

PASSWORD = "correct horse battery staple"  # nosec B105 — тестовый пароль


@lru_cache(maxsize=1)
def password_hash() -> str:
    return hash_password(PASSWORD)


async def make_user(
    session: AsyncSession,
    *roles: SystemRole,
    status: UserStatus = UserStatus.ACTIVE,
    password_hash_value: str | None = "default",  # noqa: S107
    source: UserSource = UserSource.LOCAL,
) -> User:
    login = f"u.{uuid.uuid4().hex[:12]}"
    hashed = password_hash() if password_hash_value == "default" else password_hash_value
    user = User(
        login=login,
        full_name=f"Тест {login}",
        status=status,
        source=source,
        password_hash=hashed if source is UserSource.LOCAL else None,
        block_reason=UserBlockReason.MANUAL if status is UserStatus.BLOCKED else None,
    )
    session.add(user)
    await session.flush()
    for role in roles:
        session.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    await session.flush()
    return user
