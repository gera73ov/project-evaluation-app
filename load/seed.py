"""QA-019 · данные и сессии для нагрузочного теста (load/locustfile.py; SPEC NFR-PERF-01).

Запуск из каталога backend с теми же DATABASE_URL, REDIS_URL и ENCRYPTION_KEY, что у API стенда:

    uv run --frozen python ../load/seed.py > ../load/slots.json

или одноразовым контейнером из образа api (так делает load/run.sh):

    docker compose ... run --rm --no-deps -T -v "$PWD/load:/load:ro" api python /load/seed.py

Профиль NFR-PERF-01: 300 пользователей в системе, до 30 активных проектов, до 15 человек в одном
проекте. Создаёт (повторный запуск ничего не дублирует):

* демо-данные ``seed-demo``, если их ещё нет: из них берётся «Нагрузочный тест (2 000 узлов)»;
* модератора ``load.moderator`` и 300 экспертов ``load.u001`` … ``load.u300`` без пароля для входа;
* ещё 29 проектов «Нагрузка NN» по ``--nodes`` узлов (по умолчанию 300) в статусе «Оценка»;
* команды по 15 экспертов (половина — «Бэкенд», половина — «Фронтенд»). Эксперт может быть в
  двух проектах: 30 × 15 = 450 мест на 300 человек.

Сессии создаются напрямую (SessionService), без входа паролем: лимит входа с одного IP (20 в
минуту) иначе не пустил бы 50 пользователей Locust. Печатает JSON со «слотами»: пользователь,
cookie сессии, CSRF-токен, проект и листья, которые правит только он (правки разных
пользователей не конфликтуют, как в жизни: эксперт правит свои строки). Слоты упорядочены так,
что первые 15 — в проекте на 2 000 узлов, остальные идут по кругу по прочим проектам.

Только для стендов: на ``APP_ENV=prod`` скрипт отказывается работать. Файл со слотами содержит
действующие сессии — не коммитьте его (он в .gitignore) и удаляйте после прогона.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import secrets
import sys
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

USERS = 300
PROJECTS = 30
TEAM = 15
DISCIPLINES = ("Бэкенд", "Фронтенд")
PHASES = ("Разработка", "Тестирование")
MODERATOR = "load.moderator"
PREFIX = "Нагрузка"
LEAVES_PER_SLOT = 40  # листьев на пользователя в слотах: столько он успеет править за прогон


def _login(i: int) -> str:
    return f"load.u{i:03d}"


async def _ensure_users(db: AsyncSession) -> tuple[Any, list[Any]]:
    from estimator.auth.providers.local import hash_password
    from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
    from estimator.db.models.users import User, UserRole

    # Пароль никто не знает: пользователи нагрузки входят только сессиями из этого скрипта
    hashed = hash_password(secrets.token_urlsafe(24))
    now = dt.datetime.now(dt.UTC)
    wanted = [(MODERATOR, "Нагрузка Модератор")] + [
        (_login(i), f"Нагрузка Эксперт {i:03d}") for i in range(1, USERS + 1)
    ]
    existing = {
        u.login: u
        for u in (
            await db.scalars(select(User).where(User.login.in_([w[0] for w in wanted])))
        ).all()
    }
    for login, name in wanted:
        if login in existing:
            continue
        user = User(
            login=login,
            full_name=name,
            email=f"{login}@example.test",
            status=UserStatus.ACTIVE,
            source=UserSource.LOCAL,
            password_hash=hashed,
            password_changed_at=now,
        )
        db.add(user)
        existing[login] = user
    await db.flush()
    moderator = existing[MODERATOR]
    has_role = await db.scalar(
        select(func.count()).where(
            UserRole.user_id == moderator.id, UserRole.role == SystemRole.MODERATOR
        )
    )
    if not has_role:
        db.add(UserRole(user_id=moderator.id, role=SystemRole.MODERATOR, source=RoleSource.MANUAL))
    return moderator, [existing[_login(i)] for i in range(1, USERS + 1)]


async def _small_project(db: AsyncSession, owner: Any, name: str, nodes: int) -> Any:
    """Проект «Оценка» на ``nodes`` живых узлов: модули по 9 функций в 4 ветках."""
    from estimator.cli.seed_demo import _branches, _finish_branches, _item, _skeleton
    from estimator.db.enums import ProjectStatus
    from estimator.db.models.tree import Node
    from estimator.services.projects import totals
    from estimator.services.tree.positions import keys_after

    project = await _skeleton(db, owner, name, list(PHASES), list(DISCIPLINES))
    project.status = ProjectStatus.ESTIMATION
    branches = list((await _branches(db, project.id)).values())
    existing = await db.scalar(
        select(func.count()).where(Node.project_id == project.id, Node.deleted_at.is_(None))
    )
    budget = nodes - int(existing or 0)
    modules = max(1, budget // 10)
    per_branch = [modules // len(branches) + (i < modules % len(branches)) for i in range(4)]
    for branch, count in zip(branches, per_branch, strict=False):
        for i, position in enumerate(keys_after(None, count), start=1):
            module = _item(
                project.id, branch, owner.id, title=f"Модуль {i}", position=position, multiplier=1
            )
            db.add(module)
            for j, pos in enumerate(keys_after(None, 9), start=1):
                db.add(
                    _item(
                        project.id,
                        module,
                        owner.id,
                        title=f"Функция {i}.{j}",
                        position=pos,
                        o=Decimal(2 + j % 3),
                        r=Decimal(4 + j % 3),
                        p=Decimal(8 + j % 5),
                        multiplier=1,
                    )
                )
        await db.flush()
    await _finish_branches(
        db, project.id, {(b.phase_id, b.discipline_id) for b in branches}, owner.id
    )
    await db.flush()
    await totals.recompute(db, project.id)
    return project


async def _ensure_projects(db: AsyncSession, owner: Any, nodes: int) -> list[Any]:
    from estimator.cli.seed_demo import LOAD, seed_demo
    from estimator.db.models.projects import Project

    big = await db.scalar(select(Project).where(Project.name == LOAD))
    if big is None:
        await seed_demo(db, secrets.token_urlsafe(12))
        big = await db.scalar(select(Project).where(Project.name == LOAD))
    projects = [big]
    for n in range(1, PROJECTS):
        name = f"{PREFIX} {n:02d} ({nodes} узлов)"
        project = await db.scalar(select(Project).where(Project.name == name))
        if project is None:
            project = await _small_project(db, owner, name, nodes)
        projects.append(project)
    return projects


def _team_of(index: int, users: list[Any]) -> list[Any]:
    """15 экспертов проекта: проект 0 — u001…u015, остальные — по кругу из u016…u300."""
    if index == 0:
        return users[:TEAM]
    rest = users[TEAM:]
    start = (index - 1) * TEAM
    return [rest[(start + k) % len(rest)] for k in range(TEAM)]


async def _ensure_teams(
    db: AsyncSession, projects: list[Any], users: list[Any], owner: Any
) -> dict:
    """Команды и раздача листьев: {(проект, пользователь): [id листьев]}."""
    from estimator.db.enums import NodeKind, ProjectRole
    from estimator.db.models.dictionaries import Discipline
    from estimator.db.models.projects import ProjectMember
    from estimator.db.models.tree import Node

    disciplines = {
        d.name: d.id
        for d in (await db.scalars(select(Discipline).where(Discipline.name.in_(DISCIPLINES))))
    }
    assigned: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = {}
    for index, project in enumerate(projects):
        team = _team_of(index, users)
        members = {
            (m.user_id, m.discipline_id)
            for m in (
                await db.scalars(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.role == ProjectRole.EXPERT,
                    )
                )
            )
        }
        by_discipline: dict[uuid.UUID, list[Any]] = {}
        for k, user in enumerate(team):
            discipline = disciplines[DISCIPLINES[k % len(DISCIPLINES)]]
            by_discipline.setdefault(discipline, []).append(user)
            if (user.id, discipline) not in members:
                db.add(
                    ProjectMember(
                        project_id=project.id,
                        user_id=user.id,
                        role=ProjectRole.EXPERT,
                        discipline_id=discipline,
                        created_by=owner.id,
                        updated_by=owner.id,
                    )
                )
        # Листья: элементы без живых детей в ветках дисциплины, по кругу между её экспертами
        child = Node.__table__.alias("child")
        has_children = (
            select(child.c.id)
            .where(child.c.parent_id == Node.id, child.c.deleted_at.is_(None))
            .exists()
        )
        for discipline, people in by_discipline.items():
            leaves = (
                await db.scalars(
                    select(Node.id)
                    .where(
                        Node.project_id == project.id,
                        Node.kind == NodeKind.ITEM,
                        Node.discipline_id == discipline,
                        Node.deleted_at.is_(None),
                        ~has_children,
                    )
                    .order_by(Node.id)
                )
            ).all()
            for k, leaf in enumerate(leaves):
                person = people[k % len(people)]
                bucket = assigned.setdefault((project.id, person.id), [])
                if len(bucket) < LEAVES_PER_SLOT:
                    bucket.append(str(leaf))
    await db.flush()
    return assigned


async def _sessions(db: AsyncSession, users: list[Any]) -> dict[uuid.UUID, tuple[str, str]]:
    from estimator.auth.policy import SessionPolicy
    from estimator.auth.sessions.service import SessionService
    from estimator.config import get_settings
    from estimator.redis_client import make_redis

    redis = make_redis(get_settings())
    try:
        service = SessionService(redis)
        out = {}
        for user in users:
            sid, record = await service.create(
                db,
                user.id,
                [],
                SessionPolicy(),
                ip="127.0.0.1",
                user_agent="locust (QA-019)",
                mfa_passed=True,
            )
            out[user.id] = (sid, record.csrf)
        return out
    finally:
        await redis.aclose()


async def _mark_setup(db: AsyncSession) -> None:
    """Отметить мастер первичной настройки завершённым (только для одноразовых стендов)."""
    now = dt.datetime.now(dt.UTC).isoformat()
    await db.execute(
        text(
            "INSERT INTO system_settings (key, value) VALUES ('app.setup', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = system_settings.value || EXCLUDED.value "
            "WHERE NOT (system_settings.value ? 'completed_at') "
            "OR system_settings.value->>'completed_at' IS NULL"
        ),
        {"v": json.dumps({"completed_at": now, "steps_done": []})},
    )


async def seed(nodes: int, mark_setup: bool) -> dict[str, Any]:
    from estimator.config import get_settings
    from estimator.db.session import dispose_engine, transaction

    if get_settings().app_env == "prod":
        raise SystemExit("Отказ: нагрузочные данные не создаются на APP_ENV=prod")
    try:
        async with transaction() as db:
            if mark_setup:
                await _mark_setup(db)
            moderator, users = await _ensure_users(db)
            projects = await _ensure_projects(db, moderator, nodes)
            assigned = await _ensure_teams(db, projects, users, moderator)
            slots_by_project = [
                [(p, u) for u in _team_of(i, users) if assigned.get((p.id, u.id))]
                for i, p in enumerate(projects)
            ]
            order = list(slots_by_project[0])
            rest = slots_by_project[1:]
            for k in range(TEAM):
                order += [team[k] for team in rest if k < len(team)]
            sessions = await _sessions(db, list({u.id: u for _, u in order}.values()))
        slots = [
            {
                "login": u.login,
                "user_id": str(u.id),
                "session": sessions[u.id][0],
                "csrf": sessions[u.id][1],
                "project_id": str(p.id),
                "leaves": assigned[(p.id, u.id)],
            }
            for p, u in order
        ]
        return {
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "projects": [{"id": str(p.id), "name": p.name} for p in projects],
            "slots": slots,
        }
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--nodes", type=int, default=300, help="узлов в каждом из 29 проектов")
    parser.add_argument(
        "--mark-setup",
        action="store_true",
        help="отметить мастер первичной настройки завершённым (одноразовый стенд без мастера)",
    )
    args = parser.parse_args()
    from estimator.logging import configure_logging

    configure_logging("WARNING", stream="stderr")  # в stdout — только JSON со слотами
    data = asyncio.run(seed(args.nodes, args.mark_setup))
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    print(
        f"слотов: {len(data['slots'])}, проектов: {len(data['projects'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
