"""DB-012: ``estimator seed-demo`` — пользователи всех ролей, «Портал дилеров» с итогом 6.5,
проект на 2 000 узлов; повторный запуск ничего не дублирует."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.cli import seed_demo
from estimator.db.enums import SystemRole
from estimator.db.models.tree import Node
from estimator.db.models.users import User, UserRole
from tests.integration.core.conftest import World

pytestmark = [pytest.mark.integration, pytest.mark.spec("17.4")]


def _tenth(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.1"))


@pytest.mark.spec("6.5")
async def test_seed_demo(world: World, db_session: AsyncSession) -> None:
    result = await seed_demo.seed_demo(db_session, "demo-password-1")
    assert len(result.users_created) == 12
    roles = set(
        (
            await db_session.scalars(
                select(UserRole.role)
                .join(User, User.id == UserRole.user_id)
                .where(User.login.like("demo.%"))
            )
        ).all()
    )
    assert roles == set(SystemRole)

    smirnova = await db_session.scalar(select(User.id).where(User.login == "demo.smirnova"))
    moderator = await world.session_for(smirnova, SystemRole.MODERATOR)
    portal = result.projects[seed_demo.PORTAL]
    tree = await moderator.get(f"/projects/{portal}/tree")
    assert tree.status_code == 200, tree.text
    total = tree.json()["totals"]["total"]
    assert (_tenth(total["e"]), _tenth(total["p80"]), _tenth(total["p90"])) == (
        Decimal("406.5"),
        Decimal("425.5"),
        Decimal("435.5"),
    )
    money = (await moderator.get(f"/projects/{portal}/money")).json()
    assert (money["currency"], money["exchange_rate"], money["vat_percent"]) == (
        "USD",
        "92.5",
        "20",
    )
    assert money["rates_missing"] == []
    home = (await moderator.get("/projects")).json()["items"]
    [item] = [i for i in home if i["id"] == str(portal)]
    assert _tenth(item["quote_hours"]) == Decimal("425.5")

    load = result.projects[seed_demo.LOAD]
    count = await db_session.scalar(
        select(func.count()).where(Node.project_id == load, Node.deleted_at.is_(None))
    )
    assert count == seed_demo.LOAD_NODES

    again = await seed_demo.seed_demo(db_session, "demo-password-1")
    assert again.users_created == []
    assert set(again.skipped) == {seed_demo.PORTAL, seed_demo.LOAD}
