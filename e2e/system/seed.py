"""FE-094 · данные для Playwright-сценариев системной части (e2e/system).

Запуск из каталога backend, с теми же DATABASE_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/system/seed.py

Создаёт с уникальными логинами суперадминистратора и аудитора ИБ с подключённым TOTP (общий
секрет печатается: сценарий считает коды сам) и заблокированного пользователя без ролей — цель
анонимизации. Мастер первичной настройки отмечается завершённым, все шаги пройдены. Печатает
JSON; его читает global-setup.ts. Только для dev и тестовых стендов.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets

from sqlalchemy import text

from estimator.admin.setup import ALL_MARKS
from estimator.auth.providers.local import hash_password
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.db.enums import RoleSource, SystemRole, UserBlockReason, UserSource, UserStatus
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
        "superadmin": (f"e2e.sa.{suffix}", f"Суперов С. {suffix}"),
        "auditor": (f"e2e.aud.{suffix}", f"Аудиторова А. {suffix}"),
        "blocked": (f"e2e.blk.{suffix}", f"Уволенный У. {suffix}"),
    }
    roles = {
        "superadmin": SystemRole.SUPERADMIN,
        "auditor": SystemRole.SECURITY_AUDITOR,
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
                # все шаги пройдены: иначе суперадминистратора уводит в мастер первичной настройки
                {"v": json.dumps({"completed_at": now.isoformat(), "steps_done": list(ALL_MARKS)})},
            )
            ids: dict[str, str] = {}
            for kind, (login, full_name) in people.items():
                user = User(
                    login=login,
                    email=f"{login}@example.test",
                    full_name=full_name,
                    status=UserStatus.BLOCKED if kind == "blocked" else UserStatus.ACTIVE,
                    source=UserSource.LOCAL,
                    password_hash=hashed,
                    password_changed_at=now,
                )
                if kind == "blocked":
                    user.block_reason = UserBlockReason.MANUAL
                    user.blocked_at = now
                db.add(user)
                await db.flush()
                ids[kind] = str(user.id)
                role = roles.get(kind)
                if role is not None:
                    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, totp)
                    user.totp_enabled = True
                    db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
    finally:
        await dispose_engine()
    return {
        **{
            kind: {"id": ids[kind], "login": login, "name": name}
            for kind, (login, name) in people.items()
        },
        "suffix": suffix,
        "password": password,
        "totp": totp,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))  # вывод читает global-setup.ts
