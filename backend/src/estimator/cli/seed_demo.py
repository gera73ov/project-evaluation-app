"""``estimator seed-demo`` — демо-данные для стендов (DB-012; SPEC 17.4, 18.1, 5.1, 6.5).

Только для стендов (``stand_only``): на ``APP_ENV=prod`` команда отказывается работать.

* Справочники по умолчанию кладёт миграция (DB-010); команда проверяет, что они есть.
* 12 пользователей всех ролей (логины ``demo.*``) с общим паролем: ``--password`` или
  переменная ``DEMO_PASSWORD``; без них пароль генерируется и печатается один раз.
* «Портал дилеров» — дерево 5.1, ставки 6.5, USD по 92,5, НДС 20%, статус «Оценка»; итог
  406,5 / 425,5 / 435,5 ч. Данные — из эталонной фикстуры расчёта
  contracts/fixtures/calc/portal-dilerov.json (:func:`fixture_path`).
* «Нагрузочный тест (2 000 узлов)» — ровно 2 000 живых узлов для нагрузочных тестов.

Повторный запуск ничего не дублирует: существующие пользователи и проекты пропускаются. Каркас
проекта (фазы, ветки, деньги по умолчанию) создают сервисы CORE; узлы, команда и статусы веток
пишутся напрямую, как при копировании проекта (CORE-023), без событий и уведомлений: команда
работает без брокера и WebSocket.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import typer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.context import Principal
from estimator.db.enums import (
    BranchStatusValue,
    NodeKind,
    ProjectRole,
    ProjectStatus,
    RoleSource,
    SystemRole,
    UserSource,
    UserStatus,
)

PORTAL = "Портал дилеров"
LOAD = "Нагрузочный тест (2 000 узлов)"
LOAD_NODES = 2000
CUSTOMER = "ООО «Дилерская сеть»"
EXIT_REFUSED = 1

#: (логин, ФИО, системные роли)
USERS: tuple[tuple[str, str, tuple[SystemRole, ...]], ...] = (
    ("demo.superadmin", "Суперадминистратор (демо)", (SystemRole.SUPERADMIN,)),
    ("demo.kozlov", "Козлов Виктор", (SystemRole.ADMIN,)),
    ("demo.smirnova", "Смирнова Анна", (SystemRole.MODERATOR,)),
    ("demo.ivanov", "Иванов Илья", (SystemRole.MODERATOR,)),
    ("demo.petrov", "Петров Павел", ()),
    ("demo.kuznetsova", "Кузнецова Ольга", ()),
    ("demo.volkov", "Волков Дмитрий", ()),
    ("demo.orlova", "Орлова Мария", ()),
    ("demo.belov", "Белов Никита", ()),
    ("demo.sidorov", "Сидоров Пётр", (SystemRole.PRESALE,)),
    ("demo.sokolova", "Соколова Елена", (SystemRole.PRESALE_HEAD,)),
    ("demo.frolova", "Фролова Людмила", (SystemRole.SECURITY_AUDITOR,)),
)

#: Команда «Портала дилеров»: (логин, роль, дисциплина фикстуры, ревьюер)
TEAM: tuple[tuple[str, ProjectRole, str | None, bool], ...] = (
    ("demo.smirnova", ProjectRole.MODERATOR, None, False),
    ("demo.sidorov", ProjectRole.PRESALE, None, False),
    ("demo.kuznetsova", ProjectRole.EXPERT, "d-analytics", False),
    ("demo.volkov", ProjectRole.EXPERT, "d-arch", False),
    ("demo.ivanov", ProjectRole.EXPERT, "d-backend", False),
    ("demo.belov", ProjectRole.EXPERT, "d-backend", True),
    ("demo.petrov", ProjectRole.EXPERT, "d-frontend", False),
    ("demo.orlova", ProjectRole.EXPERT, "d-qa", False),
)


FIXTURE = "portal-dilerov.json"
ENV_FIXTURE = "ESTIMATOR_DEMO_FIXTURE"


def fixture_path() -> Path:
    """Фикстура «Портала дилеров» (CORE-001): переменная :data:`ENV_FIXTURE`, файл рядом с
    модулем (образ) или ``contracts/fixtures/calc`` в репозитории — как ws-events.schema.json."""
    env = os.environ.get(ENV_FIXTURE)
    if env:
        return Path(env)
    packaged = Path(__file__).with_name(FIXTURE)
    if packaged.is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "fixtures" / "calc" / FIXTURE
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"не найден {FIXTURE}: задайте {ENV_FIXTURE}")


@dataclass
class SeedResult:
    users_created: list[str] = field(default_factory=list)
    projects: dict[str, uuid.UUID] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


def _principal(user_id: uuid.UUID, login: str, full_name: str) -> Principal:
    """Принципал для сервисов CORE (без HTTP-сессии; сессия сервисам не нужна)."""
    return Principal(
        user_id=user_id,
        login=login,
        full_name=full_name,
        roles=frozenset({SystemRole.MODERATOR}),
        session_id="seed-demo",
        session=cast(Any, None),
        mfa_passed=True,
    )


async def _users(db: AsyncSession, password: str, result: SeedResult) -> dict[str, Any]:
    from estimator.auth.providers.local import hash_password
    from estimator.db.models.users import User, UserRole

    hashed = hash_password(password)
    out: dict[str, Any] = {}
    now = dt.datetime.now(dt.UTC)
    for login, name, roles in USERS:
        user = await db.scalar(select(User).where(User.login == login))
        if user is None:
            user = User(
                login=login,
                full_name=name,
                email=f"{login}@example.local",
                status=UserStatus.ACTIVE,
                source=UserSource.LOCAL,
                password_hash=hashed,
                password_changed_at=now,
            )
            db.add(user)
            await db.flush()
            for role in roles:
                db.add(UserRole(user_id=user.id, role=role, source=RoleSource.MANUAL))
            result.users_created.append(login)
        out[login] = user
    await db.flush()
    return out


async def _check_dictionaries(db: AsyncSession) -> None:
    from estimator.db.models.dictionaries import Discipline, NodeType, Phase

    for model in (Phase, Discipline, NodeType):
        if not await db.scalar(select(func.count()).select_from(model)):
            raise RuntimeError("справочники пусты: сначала выполните «estimator migrate» (DB-010)")


async def _skeleton(
    db: AsyncSession,
    owner: Any,
    name: str,
    phase_names: list[str],
    discipline_names: list[str],
) -> Any:
    """Проект в «Подготовке» через сервисы CORE: фазы, ветки дисциплин, деньги по умолчанию."""
    from estimator.db.models.dictionaries import Discipline, Phase
    from estimator.services import projects
    from estimator.services.projects.disciplines import add_discipline

    phases = {p.name: p.id for p in (await db.scalars(select(Phase))).all()}
    disciplines = {d.name: d.id for d in (await db.scalars(select(Discipline))).all()}
    principal = _principal(owner.id, owner.login, owner.full_name)
    project = await projects.create_project(
        db,
        principal,
        projects.NewProject(
            name=name, customer=CUSTOMER, phase_ids=[phases[n] for n in phase_names]
        ),
    )
    await db.flush()
    for d in discipline_names:
        await add_discipline(db, principal, project, disciplines[d], publish_project=False)
    await db.flush()
    return project


async def _branches(db: AsyncSession, project_id: uuid.UUID) -> dict[tuple[str, str], Any]:
    """Ветки дисциплин: (название фазы, название дисциплины) → узел."""
    from estimator.db.models.dictionaries import Discipline, Phase
    from estimator.db.models.tree import Node

    rows = await db.execute(
        select(Node, Phase.name, Discipline.name)
        .join(Phase, Phase.id == Node.phase_id)
        .join(Discipline, Discipline.id == Node.discipline_id)
        .where(Node.project_id == project_id, Node.kind == NodeKind.DISCIPLINE)
    )
    return {(ph, d): node for node, ph, d in rows.all()}


async def _finish_branches(
    db: AsyncSession, project_id: uuid.UUID, filled: set[tuple[uuid.UUID, uuid.UUID]], user_id: Any
) -> None:
    """Ветки с узлами — «черновик», пустые — «не нужно»."""
    from estimator.db.models.projects import BranchStatus

    for row in (
        await db.scalars(select(BranchStatus).where(BranchStatus.project_id == project_id))
    ).all():
        key = (row.phase_id, row.discipline_id)
        row.status = BranchStatusValue.DRAFT if key in filled else BranchStatusValue.NOT_NEEDED
        row.changed_by = user_id


def _item(project_id: uuid.UUID, parent: Any, user_id: Any, **values: Any) -> Any:
    from estimator.db.models.tree import Node
    from estimator.db.uuid7 import uuid7

    return Node(
        id=uuid7(),
        project_id=project_id,
        parent_id=parent.id,
        kind=NodeKind.ITEM,
        phase_id=parent.phase_id,
        discipline_id=parent.discipline_id,
        self_review=False,
        version=1,
        field_versions={},
        created_by=user_id,
        updated_by=user_id,
        **values,
    )


async def _team(
    db: AsyncSession, project_id: uuid.UUID, users: dict[str, Any], disciplines: dict[str, Any]
) -> None:
    from estimator.db.models.projects import ProjectMember

    owner = users["demo.smirnova"].id
    for login, role, discipline, reviewer in TEAM:
        if role is ProjectRole.MODERATOR:
            continue  # создатель уже модератор (create_project)
        db.add(
            ProjectMember(
                project_id=project_id,
                user_id=users[login].id,
                role=role,
                discipline_id=None if discipline is None else disciplines[discipline],
                is_reviewer=reviewer,
                created_by=owner,
                updated_by=owner,
            )
        )


async def _portal(db: AsyncSession, users: dict[str, Any]) -> Any:
    from estimator.db.models.dictionaries import Discipline, NodeType
    from estimator.services import money
    from estimator.services.tree.positions import keys_after

    data = json.loads(fixture_path().read_text(encoding="utf-8"))["input"]
    owner = users["demo.smirnova"]
    phase_names = {p["id"]: p["name"] for p in data["phases"]}
    discipline_names = {d["id"]: d["name"] for d in data["disciplines"]}
    project = await _skeleton(
        db,
        owner,
        PORTAL,
        [p["name"] for p in data["phases"] if not p["is_cross_cutting"]],
        list(discipline_names.values()),
    )
    project.pm_percent = Decimal(data["project"]["pm_percent"])
    project.quote_figure = data["project"]["quote_figure"]
    project.detail_level = data["project"]["detail_level"]
    project.status = ProjectStatus.ESTIMATION

    by_name = {d.name: d.id for d in (await db.scalars(select(Discipline))).all()}
    disciplines = {fid: by_name[name] for fid, name in discipline_names.items()}
    types = {
        t.name: t.id
        for t in (await db.scalars(select(NodeType).where(NodeType.project_id.is_(None)))).all()
    }
    branches = await _branches(db, project.id)
    created: dict[str, Any] = {}
    children: dict[str, list[dict[str, Any]]] = {}
    for n in data["nodes"]:
        if n["kind"] == "discipline":
            created[n["id"]] = branches[
                (phase_names[n["phase_id"]], discipline_names[n["discipline_id"]])
            ]
        elif n["kind"] == "item":
            children.setdefault(n["parent_id"], []).append(n)
    filled: set[tuple[uuid.UUID, uuid.UUID]] = set()
    pending = [pid for pid in children if pid in created]
    while pending:
        parent_key = pending.pop(0)
        parent = created[parent_key]
        items = children[parent_key]
        for n, position in zip(items, keys_after(None, len(items)), strict=True):
            node = _item(
                project.id,
                parent,
                owner.id,
                title=n["title"],
                type_id=types.get(n["type"]) if n["type"] else None,
                position=position,
                o=Decimal(n["o"]) if n.get("o") is not None else None,
                r=Decimal(n["r"]) if n.get("r") is not None else None,
                p=Decimal(n["p"]) if n.get("p") is not None else None,
                multiplier=n.get("multiplier", 1),
            )
            db.add(node)
            created[n["id"]] = node
            filled.add((node.phase_id, node.discipline_id))
            if n["id"] in children:
                pending.append(n["id"])
        await db.flush()
    await _finish_branches(db, project.id, filled, owner.id)
    await _team(db, project.id, users, disciplines)
    m = data["money"]
    await money.set_settings(
        db,
        project.id,
        owner.id,
        currency=m["currency"],
        exchange_rate=Decimal(m["exchange_rate"]),
        vat_percent=Decimal(m["vat_percent"]) if m["vat_percent"] is not None else None,
        rates={
            None if r["discipline_id"] is None else disciplines[r["discipline_id"]]: Decimal(
                r["rate_rub"]
            )
            for r in m["rates"]
        },
    )
    return project


async def _load_project(db: AsyncSession, users: dict[str, Any]) -> Any:
    """Проект ровно на :data:`LOAD_NODES` живых узлов: модули по 9 функций в 4 ветках."""
    from estimator.db.models.tree import Node
    from estimator.services.tree.positions import keys_after

    owner = users["demo.ivanov"]
    project = await _skeleton(
        db, owner, LOAD, ["Разработка", "Тестирование"], ["Бэкенд", "Фронтенд"]
    )
    project.status = ProjectStatus.ESTIMATION
    branches = list((await _branches(db, project.id)).values())
    existing = await db.scalar(
        select(func.count()).where(Node.project_id == project.id, Node.deleted_at.is_(None))
    )
    budget = LOAD_NODES - int(existing or 0)
    per_module = 10  # модуль + 9 функций
    filled: set[tuple[uuid.UUID, uuid.UUID]] = set()
    modules: list[tuple[Any, int]] = []  # (ветка, функций в модуле)
    while budget > 0:
        leaves = min(per_module, budget) - 1
        modules.append((branches[len(modules) % len(branches)], leaves))
        budget -= leaves + 1
    by_branch: dict[uuid.UUID, list[int]] = {}
    for branch, leaves in modules:
        by_branch.setdefault(branch.id, []).append(leaves)
    for branch in branches:
        counts = by_branch.get(branch.id, [])
        for i, (leaves, position) in enumerate(
            zip(counts, keys_after(None, len(counts)), strict=True), start=1
        ):
            module = _item(
                project.id,
                branch,
                owner.id,
                title=f"Модуль {i}",
                position=position,
                multiplier=1,
                **({} if leaves else {"o": Decimal(8), "r": Decimal(12), "p": Decimal(20)}),
            )
            db.add(module)
            for j, pos in enumerate(keys_after(None, leaves), start=1):
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
            filled.add((branch.phase_id, branch.discipline_id))
        await db.flush()
    await _finish_branches(db, project.id, filled, owner.id)
    return project


async def seed_demo(db: AsyncSession, password: str) -> SeedResult:
    """Создать демо-данные в транзакции ``db`` (без commit)."""
    from estimator.db.models.projects import Project
    from estimator.services.projects import totals

    result = SeedResult()
    await _check_dictionaries(db)
    users = await _users(db, password, result)
    for name, build in ((PORTAL, _portal), (LOAD, _load_project)):
        existing = await db.scalar(select(Project.id).where(Project.name == name))
        if existing is not None:
            result.skipped.append(name)
            result.projects[name] = existing
            continue
        project = await build(db, users)
        await db.flush()
        await totals.recompute(db, project.id)  # кэш итогов для «Моих оценок» (CORE-026)
        result.projects[name] = project.id
    return result


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command(
        "seed-demo",
        stand_only=True,
        help="Демо-данные для стендов: 12 пользователей, «Портал дилеров», проект на 2 000 узлов.",
    )
    def seed_demo_cmd(
        password: str | None = typer.Option(
            None,
            "--password",
            envvar="DEMO_PASSWORD",
            help="Пароль демо-пользователей; без него генерируется и печатается.",
        ),
    ) -> None:
        from estimator.db.session import dispose_engine, get_sessionmaker

        secret = password or secrets.token_urlsafe(12)

        async def main() -> SeedResult:
            try:
                # без хуков after-commit: событиям и очередям на стенде без брокера некуда идти
                async with get_sessionmaker()() as db, db.begin():
                    return await seed_demo(db, secret)
            finally:
                await dispose_engine()

        try:
            result = asyncio.run(main())
        except RuntimeError as exc:
            typer.echo(f"Отказ: {exc}", err=True)
            raise typer.Exit(EXIT_REFUSED) from exc
        typer.echo(f"Пользователи созданы: {len(result.users_created)}")
        if result.users_created and password is None:
            typer.echo(f"Пароль демо-пользователей (demo.*): {secret}")
        for name, pid in result.projects.items():
            mark = " (уже был)" if name in result.skipped else ""
            typer.echo(f"{name}: {pid}{mark}")
