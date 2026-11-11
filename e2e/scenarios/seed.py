"""QA-018 · данные сквозных сценариев ролей (e2e/scenarios).

Запуск из каталога backend, с теми же DATABASE_URL, REDIS_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../e2e/scenarios/seed.py

Создаёт с уникальными логинами и одним секретом TOTP (сценарий считает коды сам):

* модератора, двух экспертов одной дисциплины и пресейла — участников сквозного процесса 4.1;
* руководителя пресейла и проект модератора в статусе «Архив» (G-21);
* второго модератора с проектом и сессией без пройденного TOTP (G-19): вход паролем такую
  сессию не даёт (у пользователя с TOTP вход всегда спрашивает код), поэтому сид создаёт её
  напрямую, как вход до включения политики TOTP; сценарий кладёт её cookie в браузер.

Мастер первичной настройки отмечается завершённым. Печатает JSON; его читает global-setup.ts.
Только для dev и тестовых стендов.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets

from sqlalchemy import text

from estimator.auth.policy import SessionPolicy
from estimator.auth.providers.local import hash_password
from estimator.auth.sessions.service import SessionService
from estimator.auth.totp import encrypt_secret, new_secret
from estimator.cli.seed_demo import _skeleton
from estimator.config import get_settings
from estimator.db.enums import ProjectStatus, RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.db.session import dispose_engine, transaction
from estimator.redis_client import make_redis
from estimator.security.crypto import get_cipher


async def seed() -> dict[str, object]:
    suffix = secrets.token_hex(4)
    password = f"e2e-{secrets.token_urlsafe(12)}"
    hashed = hash_password(password)
    now = dt.datetime.now(dt.UTC)
    totp = new_secret()
    people = {
        "moderator": (f"e2e.smod.{suffix}", f"Сквозной М. {suffix}", [SystemRole.MODERATOR], True),
        "expert1": (f"e2e.sexa.{suffix}", f"Экспертная А. {suffix}", [], False),
        "expert2": (f"e2e.sexb.{suffix}", f"Экспертов Б. {suffix}", [], False),
        "presale": (f"e2e.spre.{suffix}", f"Пресейлова П. {suffix}", [SystemRole.PRESALE], True),
        "head": (
            f"e2e.shead.{suffix}",
            f"Руководящий Р. {suffix}",
            [SystemRole.PRESALE_HEAD],
            True,
        ),
        "moderator2": (
            f"e2e.smod2.{suffix}",
            f"Безкодова С. {suffix}",
            [SystemRole.MODERATOR],
            True,
        ),
    }
    settings = get_settings()
    redis = make_redis(settings)
    try:
        async with transaction() as db:
            await db.execute(
                text(
                    "INSERT INTO system_settings (key, value) "
                    "VALUES ('app.setup', CAST(:v AS jsonb)) "
                    "ON CONFLICT (key) DO UPDATE "
                    # шаги мастера не трогаем: system/seed.py отмечает их все, и пустой список
                    # снова увёл бы суперадминистратора в мастер настройки
                    "SET value = system_settings.value "
                    "|| jsonb_build_object('completed_at', EXCLUDED.value->'completed_at')"
                ),
                {"v": json.dumps({"completed_at": now.isoformat(), "steps_done": []})},
            )
            users: dict[str, User] = {}
            for kind, (login, full_name, roles, with_totp) in people.items():
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
                if with_totp:
                    user.totp_secret_enc = encrypt_secret(get_cipher(), user.id, totp)
                    user.totp_enabled = True
                for role in roles:
                    db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
                users[kind] = user
            await db.flush()
            phases = (
                await db.execute(
                    text(
                        "SELECT id, name FROM phases WHERE is_active AND NOT is_cross_cutting "
                        "ORDER BY sort_order LIMIT 1"
                    )
                )
            ).all()
            disciplines = (
                await db.execute(
                    text("SELECT id, name FROM disciplines WHERE is_active ORDER BY name LIMIT 1")
                )
            ).all()
            phase_names = [row.name for row in phases]
            discipline_names = [row.name for row in disciplines]
            archived_name = f"E2E архив {suffix}"
            archived = await _skeleton(
                db, users["moderator"], archived_name, phase_names, discipline_names
            )
            archived.status = ProjectStatus.ARCHIVED
            guarded = await _skeleton(
                db, users["moderator2"], f"E2E деньги {suffix}", phase_names, discipline_names
            )
            # G-19: сессия без второго фактора у пользователя с TOTP
            sid, record = await SessionService(redis).create(
                db,
                users["moderator2"].id,
                [SystemRole.MODERATOR],
                SessionPolicy(),
                ip="127.0.0.1",
                user_agent="e2e scenarios seed",
                mfa_passed=False,
            )
    finally:
        await redis.aclose()
        await dispose_engine()
    return {
        **{
            kind: {"id": str(user.id), "login": user.login, "name": user.full_name}
            for kind, user in users.items()
        },
        "phases": [str(row.id) for row in phases],
        "disciplines": [str(row.id) for row in disciplines],
        "discipline_names": discipline_names,
        "archived": {"id": str(archived.id), "name": archived_name},
        "guarded": {"id": str(guarded.id), "session": sid, "csrf": record.csrf},
        "password": password,
        "totp": totp,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))  # вывод читает global-setup.ts
