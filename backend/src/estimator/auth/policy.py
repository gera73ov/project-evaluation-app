"""Настройки безопасности, которые читает трек AUTH (contracts/settings.schema.json).

Ключи ``system_settings`` читаются напрямую (только чтение): сервис настроек с проверкой схемы и
аудитом изменений — ADM-002. Отсутствующий ключ означает значение по умолчанию из схемы.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.db.enums import SystemRole

#: Константы SPEC, не настраиваются (``x-note`` ключа ``security.session``).
PRE_MFA_SECONDS = 15 * 60  # сессия до подключения TOTP (FR-2FA-04)
STEP_UP_SECONDS = 5 * 60  # step-up (SEC-AUTH-05)
WARN_BEFORE_SECONDS = 2 * 60  # диалог «Продлить сессию?» (FR-SESS-02)

#: Роли с коротким тайм-аутом бездействия (FR-SESS-02).
ADMIN_ROLES = frozenset({SystemRole.ADMIN, SystemRole.SUPERADMIN})

_READ = text("SELECT key, value FROM system_settings WHERE key = ANY(:keys)")


async def read_settings(conn: AsyncConnection | AsyncSession, *keys: str) -> dict[str, Any]:
    """Значения ключей ``system_settings``; отсутствующих ключей в ответе нет."""
    rows = (await conn.execute(_READ, {"keys": list(keys)})).all()
    return {str(row[0]): row[1] for row in rows}


@dataclass(frozen=True)
class SessionPolicy:
    """Тайм-ауты (``security.session``) и лимит сессий (``security.password_policy``)."""

    idle_minutes_user: int = 60
    idle_minutes_admin: int = 15
    absolute_hours: int = 12
    max_sessions: int | None = None

    @classmethod
    def from_settings(
        cls,
        session: Mapping[str, Any] | None,
        password_policy: Mapping[str, Any] | None = None,
    ) -> SessionPolicy:
        base = cls()
        session = session or {}
        limit = (password_policy or {}).get("max_sessions", base.max_sessions)
        return cls(
            idle_minutes_user=int(session.get("idle_minutes_user", base.idle_minutes_user)),
            idle_minutes_admin=int(session.get("idle_minutes_admin", base.idle_minutes_admin)),
            absolute_hours=int(session.get("absolute_hours", base.absolute_hours)),
            max_sessions=int(limit) if limit is not None else None,
        )

    def idle_seconds(self, roles: Collection[SystemRole | str]) -> int:
        """Самый короткий тайм-аут среди ролей пользователя (BR-ROLE-01)."""
        minutes = self.idle_minutes_user
        if ADMIN_ROLES & {SystemRole(r) for r in roles}:
            minutes = min(minutes, self.idle_minutes_admin)
        return minutes * 60

    @property
    def absolute_seconds(self) -> int:
        return self.absolute_hours * 3600


async def load_session_policy(conn: AsyncConnection | AsyncSession) -> SessionPolicy:
    values = await read_settings(conn, "security.session", "security.password_policy")
    return SessionPolicy.from_settings(
        values.get("security.session"), values.get("security.password_policy")
    )


async def load_auth_mode(conn: AsyncConnection | AsyncSession) -> str:
    """``auth.mode``: ``local`` (по умолчанию) или ``ad``."""
    values = await read_settings(conn, "auth.mode")
    return str(values.get("auth.mode") or "local")
