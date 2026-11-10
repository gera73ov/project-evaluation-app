"""SEC-017: 2–3 активных суперадминистратора (BR-ROLE-03, Q-07, 15.3 LAST_SUPERADMIN)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.enums import SystemRole, UserStatus
from estimator.security.authz import role_rules
from tests.integration.auth.helpers import make_user

pytestmark = [pytest.mark.integration, pytest.mark.spec("BR-ROLE-03")]


@pytest.fixture
async def clean(db_session: AsyncSession) -> AsyncSession:
    """Без чужих суперадминистраторов: тест видит только своих (транзакция откатится)."""
    await db_session.execute(text("DELETE FROM user_roles WHERE role = 'superadmin'"))
    return db_session


async def test_last_active_superadmin_cannot_be_removed(clean: AsyncSession) -> None:
    first = await make_user(clean, SystemRole.SUPERADMIN)
    assert await role_rules.needs_second_superadmin(clean)
    with pytest.raises(ApiError) as exc:
        await role_rules.ensure_not_last_superadmin(clean, first.id)
    assert exc.value.code == "LAST_SUPERADMIN"

    # Ждущий пароль второй не считается активным: первого всё ещё нельзя снять
    second = await make_user(clean, SystemRole.SUPERADMIN, status=UserStatus.PENDING_PASSWORD)
    with pytest.raises(ApiError):
        await role_rules.ensure_not_last_superadmin(clean, first.id)

    second.status = UserStatus.ACTIVE
    await clean.flush()
    assert not await role_rules.needs_second_superadmin(clean)
    await role_rules.ensure_not_last_superadmin(clean, first.id)
    await role_rules.ensure_not_last_superadmin(clean, second.id)

    plain = await make_user(clean, SystemRole.ADMIN)
    await role_rules.ensure_not_last_superadmin(clean, plain.id)  # не суперадминистратор


async def test_fourth_superadmin_cannot_be_created(clean: AsyncSession) -> None:
    await make_user(clean, SystemRole.SUPERADMIN)
    await make_user(clean, SystemRole.SUPERADMIN)
    await role_rules.ensure_superadmin_slot(clean)
    await make_user(clean, SystemRole.SUPERADMIN, status=UserStatus.PENDING_PASSWORD)
    with pytest.raises(ApiError) as exc:
        await role_rules.ensure_superadmin_slot(clean)
    assert exc.value.code == "SUPERADMIN_LIMIT"
    # Заблокированный место не занимает
    await make_user(clean, SystemRole.SUPERADMIN, status=UserStatus.BLOCKED)
    assert await role_rules.superadmin_count(clean, statuses=(UserStatus.ACTIVE,)) == 2
