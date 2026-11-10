"""FE-093 · данные для сценариев статистики, снимков, сравнения и портфеля (e2e/stats).

Запуск из каталога backend, с теми же DATABASE_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/stats/seed.py

Создаёт с уникальными логинами модератора, руководителя пресейла и эксперта (адресат «Напомнить
не начавшим»), всем подключает TOTP (секрет печатается: сценарий считает коды сам), печатает id
двух фаз и двух дисциплин из справочников. Мастер первичной настройки отмечается завершённым.
Печатает JSON; его читает global-setup.ts. Узлы проекта добавляет `../perf/fill.py` после того,
как сценарий создаст проект. Только для dev и
тестовых стендов.
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
        "moderator": (f"e2e.smod.{suffix}", f"Снимков С. {suffix}"),
        "head": (f"e2e.head.{suffix}", f"Пресейлова П. {suffix}"),
        "expert": (f"e2e.sexp.{suffix}", f"Экспертов Э. {suffix}"),
    }
    roles = {"moderator": SystemRole.MODERATOR, "head": SystemRole.PRESALE_HEAD}
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
                user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, totp)
                user.totp_enabled = True
                if kind in roles:  # эксперт — без системной роли, его назначают в команду проекта
                    db.add(UserRole(user_id=user.id, role=roles[kind], source=RoleSource.MANUAL))
            phases = (
                await db.execute(
                    text(
                        "SELECT id FROM phases WHERE is_active AND NOT is_cross_cutting "
                        "ORDER BY sort_order LIMIT 2"
                    )
                )
            ).scalars()
            disciplines = (
                await db.execute(
                    text("SELECT id, name FROM disciplines WHERE is_active ORDER BY name LIMIT 2")
                )
            ).all()
            dictionaries = {
                "phases": [str(x) for x in phases],
                "disciplines": [str(row.id) for row in disciplines],
                "discipline_names": [row.name for row in disciplines],
            }
    finally:
        await dispose_engine()
    return {
        **{
            kind: {"id": ids[kind], "login": login, "name": name}
            for kind, (login, name) in people.items()
        },
        **dictionaries,
        "password": password,
        "totp": totp,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))  # вывод читает global-setup.ts
