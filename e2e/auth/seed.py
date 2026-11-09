"""FE-090 · данные для Playwright-сценариев входа (e2e/auth).

Запуск из каталога backend, с теми же DATABASE_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/auth/seed.py

Отмечает мастер первичной настройки завершённым (иначе вход закрыт, FR-SA-02) и создаёт двух
локальных пользователей с уникальными логинами: без системных ролей (TOTP не обязателен) и
администратора (TOTP обязателен, но не подключён — принудительное подключение, FR-2FA-04).
Печатает JSON с логинами и паролем; его читает global-setup.ts. Только для dev и тестовых стендов.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets

from sqlalchemy import text

from estimator.auth.providers.local import hash_password
from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.db.session import dispose_engine, transaction


async def seed() -> dict[str, str]:
    suffix = secrets.token_hex(4)
    password = f"e2e-{secrets.token_urlsafe(12)}"
    hashed = hash_password(password)
    now = dt.datetime.now(dt.UTC)
    logins = {"user": f"e2e.user.{suffix}", "admin": f"e2e.admin.{suffix}"}
    try:
        async with transaction() as db:
            await db.execute(
                text(
                    "INSERT INTO system_settings (key, value) "
                    "VALUES ('app.setup', CAST(:v AS jsonb)) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = system_settings.value || EXCLUDED.value"
                ),
                {"v": json.dumps({"completed_at": now.isoformat(), "steps_done": []})},
            )
            for kind, login in logins.items():
                user = User(
                    login=login,
                    email=f"{login}@example.test",
                    full_name=f"Тестов {kind.capitalize()}",
                    status=UserStatus.ACTIVE,
                    source=UserSource.LOCAL,
                    password_hash=hashed,
                    password_changed_at=now,
                )
                db.add(user)
                await db.flush()
                if kind == "admin":
                    db.add(
                        UserRole(user_id=user.id, role=SystemRole.ADMIN, source=RoleSource.MANUAL)
                    )
    finally:
        await dispose_engine()
    return {**logins, "password": password}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))  # вывод читает global-setup.ts
