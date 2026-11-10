"""FE-094 · данные для Playwright-сценариев админки администратора (e2e/admin).

Запуск из каталога backend, с теми же DATABASE_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/admin/seed.py

Создаёт с уникальными логинами администратора и двух модераторов с подключённым TOTP (общий
секрет печатается: сценарий считает коды сам) и пользователя без системных ролей, печатает
id двух фаз. Мастер первичной настройки отмечается завершённым. Печатает JSON; его читает
global-setup.ts. Только для dev и тестовых стендов.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets

from sqlalchemy import text

from estimator.auth.providers.local import hash_password
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.db.session import dispose_engine, transaction
from estimator.security.crypto import get_cipher


async def seed() -> dict[str, object]:
    suffix = secrets.token_hex(4)
    password = f"e2e-{secrets.token_urlsafe(12)}"
    hashed = hash_password(password)
    now = dt.datetime.now(dt.UTC)
    totp = new_secret()
    people = {
        "admin": (f"e2e.adm.{suffix}", f"Администраторов А. {suffix}"),
        "user": (f"e2e.usr.{suffix}", f"Пользователев П. {suffix}"),
        "moderator": (f"e2e.amod.{suffix}", f"Модераторова Е. {suffix}"),
        "moderator2": (f"e2e.amod2.{suffix}", f"Сменщиков С. {suffix}"),
    }
    roles = {
        "admin": SystemRole.ADMIN,
        "moderator": SystemRole.MODERATOR,
        "moderator2": SystemRole.MODERATOR,
    }
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
            ids: dict[str, str] = {}
            for kind, (login, full_name) in people.items():
                user = User(
                    login=login,
                    email=f"{login}@example.test",
                    full_name=full_name,
                    status=UserStatus.ACTIVE,
                    source=UserSource.LOCAL,
                    password_hash=hashed,
                    password_changed_at=now,
                )
                db.add(user)
                await db.flush()
                ids[kind] = str(user.id)
                role = roles.get(kind)
                if role is not None:
                    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, totp)
                    user.totp_enabled = True
                    db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
            phases = (
                await db.execute(
                    text(
                        "SELECT id FROM phases WHERE is_active AND NOT is_cross_cutting "
                        "ORDER BY sort_order LIMIT 2"
                    )
                )
            ).scalars()
            phase_ids = [str(x) for x in phases]
    finally:
        await dispose_engine()
    return {
        **{
            kind: {"id": ids[kind], "login": login, "name": name}
            for kind, (login, name) in people.items()
        },
        "phases": phase_ids,
        "suffix": suffix,
        "password": password,
        "totp": totp,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))  # вывод читает global-setup.ts
