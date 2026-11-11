"""QA-021 · подготовка сканирования OWASP ZAP (deploy/zap/README.md).

Запускается одноразовым контейнером из образа api (так делает deploy/zap/run.sh), с теми же
DATABASE_URL, REDIS_URL и ключом, что у API стенда:

    python /zap-cfg/prepare.py sessions [--mark-setup] — JSON с сессиями ролей; --mark-setup
                                               отмечает мастер настройки завершённым
    python /zap-cfg/prepare.py openapi FILE URL — копия contracts/openapi.yaml с адресом стенда URL
                                               и без операций, которые оборвали бы сканирование
                                               (выход, смена пароля и TOTP, отзыв сессий, вход и
                                               восстановление доступа)

Роли: эксперт и модератор (участники проекта «ZAP <суффикс>» в статусе «Оценка») и
администратор. Логины уникальны, сессии создаются напрямую (SessionService) с пройденным TOTP:
вход паролем упёрся бы в лимит и TOTP. Файл с сессиями не храните после прогона. Только для
стендов: на ``APP_ENV=prod`` скрипт отказывается работать.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets
import sys
from pathlib import Path
from typing import Any

import yaml

#: Префиксы путей, которые сканер с сессией не трогает: они завершают или меняют сессию и вход
EXCLUDED_PREFIXES = (
    "/auth/",
    "/me/sessions",
    "/me/password",
    "/me/totp",
    "/me/backup-codes",
)


def filtered_openapi(source: Path, base_url: str) -> dict[str, Any]:
    spec = yaml.safe_load(source.read_text(encoding="utf-8"))
    spec["servers"] = [{"url": base_url.rstrip("/") + "/api/v1"}]
    spec["paths"] = {
        path: item for path, item in spec["paths"].items() if not path.startswith(EXCLUDED_PREFIXES)
    }
    return spec


async def sessions(mark_setup: bool = False) -> dict[str, Any]:
    from sqlalchemy import select, text

    from estimator.auth.policy import SessionPolicy
    from estimator.auth.providers.local import hash_password
    from estimator.auth.sessions.service import SessionService
    from estimator.cli.seed_demo import _skeleton
    from estimator.config import get_settings
    from estimator.db.enums import (
        ProjectRole,
        ProjectStatus,
        RoleSource,
        SystemRole,
        UserSource,
        UserStatus,
    )
    from estimator.db.models.dictionaries import Discipline
    from estimator.db.models.projects import ProjectMember
    from estimator.db.models.users import User, UserRole
    from estimator.db.session import dispose_engine, transaction
    from estimator.redis_client import make_redis

    settings = get_settings()
    if settings.app_env == "prod":
        raise SystemExit("Отказ: сканирование ZAP не готовится на APP_ENV=prod")
    suffix = secrets.token_hex(4)
    now = dt.datetime.now(dt.UTC)
    hashed = hash_password(secrets.token_urlsafe(24))
    people = {
        "expert": [],
        "moderator": [SystemRole.MODERATOR],
        "admin": [SystemRole.ADMIN],
    }
    redis = make_redis(settings)
    try:
        async with transaction() as db:
            if mark_setup:
                await db.execute(
                    text(
                        "INSERT INTO system_settings (key, value) "
                        "VALUES ('app.setup', CAST(:v AS jsonb)) ON CONFLICT (key) DO UPDATE "
                        "SET value = system_settings.value || EXCLUDED.value "
                        "WHERE system_settings.value->>'completed_at' IS NULL"
                    ),
                    {"v": json.dumps({"completed_at": now.isoformat(), "steps_done": []})},
                )
            users: dict[str, Any] = {}
            for role, roles in people.items():
                login = f"zap.{role}.{suffix}"
                user = User(
                    login=login,
                    full_name=f"ZAP {role} {suffix}",
                    email=f"{login}@example.test",
                    status=UserStatus.ACTIVE,
                    source=UserSource.LOCAL,
                    password_hash=hashed,
                    password_changed_at=now,
                )
                db.add(user)
                await db.flush()
                for r in roles:
                    db.add(UserRole(user_id=user.id, role=r, source=RoleSource.MANUAL))
                users[role] = user
            await db.flush()
            project = await _skeleton(
                db, users["moderator"], f"ZAP {suffix}", ["Разработка"], ["Бэкенд"]
            )
            project.status = ProjectStatus.ESTIMATION
            backend = await db.scalar(select(Discipline.id).where(Discipline.name == "Бэкенд"))
            db.add(
                ProjectMember(
                    project_id=project.id,
                    user_id=users["expert"].id,
                    role=ProjectRole.EXPERT,
                    discipline_id=backend,
                    created_by=users["moderator"].id,
                    updated_by=users["moderator"].id,
                )
            )
            service = SessionService(redis)
            out: dict[str, Any] = {"project_id": str(project.id), "roles": {}}
            for role, user in users.items():
                sid, record = await service.create(
                    db,
                    user.id,
                    people[role],
                    SessionPolicy(),
                    ip="127.0.0.1",
                    user_agent="OWASP ZAP (QA-021)",
                    mfa_passed=True,
                )
                out["roles"][role] = {"login": user.login, "session": sid, "csrf": record.csrf}
        return out
    finally:
        await redis.aclose()
        await dispose_engine()


def main() -> None:
    from estimator.logging import configure_logging

    configure_logging("WARNING", stream="stderr")  # в stdout — только результат
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "sessions":
        json.dump(asyncio.run(sessions("--mark-setup" in sys.argv[2:])), sys.stdout)
    elif mode == "openapi" and len(sys.argv) == 4:
        spec = filtered_openapi(Path(sys.argv[2]), sys.argv[3])
        yaml.safe_dump(spec, sys.stdout, allow_unicode=True, sort_keys=False)
    else:
        raise SystemExit(__doc__)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
