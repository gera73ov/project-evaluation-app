"""QA-005 · TC-SEC-03: нет денег у эксперта, ревьюера, администратора (в режиме поддержки и вне
его) и аудитора ИБ (BR-MONEY-01, SEC-AUTHZ-04, CL-08). Обход всех GET-эндпоинтов контракта и
события шины: ни денежных ключей (``rate``, ``cost``, ``currency``, ``exchange_rate``,
``money``…), ни сумм в валюте. WS-каналы ``:money`` для этих ролей — test_ws_api.py."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.acceptance.steps.money_steps import is_money_key
from tests.integration.core.conftest import Actor, World
from tests.security.crawl import crawl, find
from tests.security.stocked import Stocked, stocked

from estimator.db.enums import SystemRole
from estimator.realtime.bus.memory import InMemoryBus

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-03"), pytest.mark.spec("BR-MONEY-01"),
              pytest.mark.spec("SEC-AUTHZ-04")]  # fmt: skip

#: Справочники администратора: валюты и ставки НДС — не деньги проекта (FR-ADM-02).
DICTIONARIES = {"/admin/currencies", "/admin/vat-rates", "/admin/method-settings"}


def _money_key(key: str, value: object) -> bool:
    """Денежный ключ со значением; флаг «ставки скопированы» (аудит копирования) — не деньги."""
    return is_money_key(key) and not isinstance(value, bool)


def _amount(text: str) -> bool:
    return any(mark in text for mark in (" ₽", " USD", " EUR"))


async def _leaks(actor: Actor, st: Stocked) -> dict[str, list[str]]:
    seen = await crawl(actor, st.ids)
    assert seen.bodies, "обход не получил ни одного ответа"
    out = {p: find(b, _money_key, _amount) for p, b in seen.bodies.items() if p not in DICTIONARIES}
    return {p: v for p, v in out.items() if v}


async def test_expert_and_reviewer(
    world: World, db_session: AsyncSession, events: InMemoryBus
) -> None:
    st = await stocked(world, db_session)
    for actor in (st.s.backend_expert, st.s.frontend_expert, st.reviewer):
        assert await _leaks(actor, st) == {}
        assert (await actor.get(f"/projects/{st.s.pid}/money")).status_code == 403
    # контроль обхода: модератору с TOTP деньги видны
    assert await _leaks(st.s.moderator, st)
    # шина: в общем канале проекта денег нет — только в :money
    base: list[Any] = events.on(f"project:{st.s.pid}")
    assert base
    assert find(base, _money_key, _amount) == []


async def test_admin_and_auditor(world: World, db_session: AsyncSession) -> None:
    st = await stocked(world, db_session)
    admin = await world.actor(SystemRole.ADMIN)
    auditor = await world.actor(SystemRole.SECURITY_AUDITOR)
    assert await _leaks(admin, st) == {}
    assert await _leaks(auditor, st) == {}
    opened = await admin.post(f"/admin/projects/{st.s.pid}/support-session",
                              json={"reason": "Проверка жалобы на расчёт итогов"})  # fmt: skip
    assert opened.status_code == 201, opened.text
    assert (await admin.get(f"/projects/{st.s.pid}/tree")).status_code == 200  # режим поддержки
    assert await _leaks(admin, st) == {}
    assert (await admin.get(f"/projects/{st.s.pid}/money")).status_code == 403
