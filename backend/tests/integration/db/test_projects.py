"""DB-005: ограничения проектов, денег и команды; каскад при удалении проекта."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.dictionaries import Discipline, DisciplineProfile, Phase, VatRate
from estimator.db.models.money import ProjectMoney, ProjectRate
from estimator.db.models.projects import (
    BranchStatus,
    Project,
    ProjectDiscipline,
    ProjectMember,
    ProjectPhase,
)
from estimator.db.models.users import User
from tests.integration.db.conftest import as_app
from tests.integration.db.test_users_constraints import _rejects

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.2")]


async def _project(session: AsyncSession, **kw: object) -> Project:
    project = Project(name="Портал дилеров", customer="ООО Ромашка", pm_percent=Decimal(18), **kw)
    session.add(project)
    await session.flush()
    return project


async def _discipline(session: AsyncSession, name: str = "Бэкенд") -> Discipline:
    return (await session.scalars(select(Discipline).where(Discipline.name == name))).one()


@pytest.mark.spec("BR-MONEY-02")
async def test_two_pm_rates_rejected(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    backend = await _discipline(db_session)
    db_session.add_all(
        [
            ProjectRate(project_id=project.id, discipline_id=None, rate_rub=Decimal(3000)),
            ProjectRate(project_id=project.id, discipline_id=backend.id, rate_rub=Decimal(2500)),
        ]
    )
    await db_session.flush()
    await _rejects(
        db_session, ProjectRate(project_id=project.id, discipline_id=None, rate_rub=Decimal(1))
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "AB"},  # 3–200 символов
        {"pm_percent": Decimal("18.3")},  # шаг 0,5
        {"pm_percent": Decimal(51)},
        {"duration_weeks": 0},
        {"cancel_reason": "коротко"},
    ],
    ids=["name", "pm-step", "pm-max", "weeks", "cancel"],
)
async def test_project_row_checks(db_session: AsyncSession, kwargs: dict) -> None:
    fields = {"name": "Проект", "customer": "Заказчик", "pm_percent": Decimal(18), **kwargs}
    await _rejects(db_session, Project(**fields))


async def test_member_rules(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    user = User(login="m.member", full_name="Участник", status="active")
    db_session.add(user)
    await db_session.flush()
    backend = await _discipline(db_session)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="moderator"))
    await db_session.flush()
    # дубль модератора (discipline_id NULL) — NULLS NOT DISTINCT
    await _rejects(
        db_session, ProjectMember(project_id=project.id, user_id=user.id, role="moderator")
    )
    # эксперт без дисциплины и ревьюер-модератор запрещены
    await _rejects(db_session, ProjectMember(project_id=project.id, user_id=user.id, role="expert"))
    await _rejects(
        db_session,
        ProjectMember(project_id=project.id, user_id=user.id, role="moderator", is_reviewer=True),
    )
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role="expert",
            discipline_id=backend.id,
            is_reviewer=True,
        )
    )
    await db_session.flush()


@pytest.mark.spec("BR-PRJ-04")
async def test_project_delete_cascades(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    backend = await _discipline(db_session)
    phase = (await db_session.scalars(select(Phase).limit(1))).one()
    profile = await db_session.get(DisciplineProfile, backend.default_profile_id)
    vat = (await db_session.scalars(select(VatRate).where(VatRate.is_default))).one()
    db_session.add_all(
        [
            ProjectMoney(project_id=project.id, vat_rate_id=vat.id, vat_percent=vat.percent),
            ProjectRate(project_id=project.id, rate_rub=Decimal(3000)),
            ProjectPhase(project_id=project.id, phase_id=phase.id),
            ProjectDiscipline(
                project_id=project.id, discipline_id=backend.id, profile_id=profile.id
            ),
            BranchStatus(project_id=project.id, phase_id=phase.id, discipline_id=backend.id),
        ]
    )
    await db_session.flush()
    await db_session.delete(project)
    await db_session.flush()
    for model in (ProjectMoney, ProjectRate, ProjectPhase, ProjectDiscipline, BranchStatus):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__


async def test_rub_requires_rate_one(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    vat = (await db_session.scalars(select(VatRate).where(VatRate.is_default))).one()
    await _rejects(
        db_session,
        ProjectMoney(project_id=project.id, vat_rate_id=vat.id, exchange_rate=Decimal("90.5")),
    )


async def test_app_role_writes_projects(db_session: AsyncSession) -> None:
    await as_app(db_session)
    project = await _project(db_session)
    vat = (await db_session.scalars(select(VatRate).where(VatRate.is_default))).one()
    db_session.add(
        ProjectMoney(
            project_id=project.id,
            vat_rate_id=vat.id,
            currency="USD",
            exchange_rate=Decimal("92.1234"),
        )
    )
    await db_session.flush()
