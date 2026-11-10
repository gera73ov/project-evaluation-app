"""ADM-007: чтение справочников — права ``dict.read`` (3.3), активные и все записи (7.5, GAP-13)."""

from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.dictionaries import method
from estimator.db.enums import SystemRole
from estimator.db.models.dictionaries import Phase
from estimator.db.models.settings import SystemSetting
from tests.integration.core.conftest import World
from tests.unit._contracts import load_json

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5"), pytest.mark.spec("3.3")]

LISTS = (
    "/admin/phases",
    "/admin/disciplines",
    "/admin/node-types",
    "/admin/profiles",
    "/admin/ratios",
    "/admin/tags",
    "/admin/currencies",
    "/admin/vat-rates",
    "/admin/loss-reasons",
)


async def test_lists_for_admin_and_plain_user(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    user = await world.actor()
    for path in LISTS:
        for actor in (admin, user):
            response = await actor.get(path)
            assert response.status_code == 200, (path, response.text)
            assert isinstance(response.json()["items"], list)

    phases = (await user.get("/admin/phases")).json()["items"]
    assert phases, "миграция DB-010 заводит фазы"
    assert sum(p["is_cross_cutting"] for p in phases) == 1
    assert [p["sort_order"] for p in phases] == sorted(p["sort_order"] for p in phases)

    types = (await user.get("/admin/node-types")).json()["items"]
    assert types[0]["is_system"] is True  # «Работа» первой
    assert all(t["project_id"] is None for t in types)

    currencies = (await user.get("/admin/currencies")).json()["items"]
    assert currencies[0]["code"] == "RUB"
    vat = (await user.get("/admin/vat-rates")).json()["items"]
    assert sum(v["is_default"] for v in vat) == 1
    assert vat[0]["percent"] is None  # «Без НДС» первой


@pytest.mark.parametrize("role", [SystemRole.SUPERADMIN, SystemRole.SECURITY_AUDITOR])
async def test_superadmin_and_auditor_do_not_see_dictionaries(
    world: World, role: SystemRole
) -> None:
    actor = await world.actor(role)
    for path in (*LISTS, "/admin/method-settings"):
        response = await actor.get(path)
        assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN"), path


async def test_include_inactive(world: World, db_session: AsyncSession) -> None:
    user = await world.actor()
    first = (await user.get("/admin/phases")).json()["items"][0]
    await db_session.execute(update(Phase).where(Phase.id == first["id"]).values(is_active=False))
    await db_session.flush()
    active = (await user.get("/admin/phases")).json()["items"]
    assert first["id"] not in {p["id"] for p in active}
    everything = (await user.get("/admin/phases?include_inactive=true")).json()["items"]
    hidden = next(p for p in everything if p["id"] == first["id"])
    assert hidden["is_active"] is False


async def test_method_settings_defaults_and_stored(world: World, db_session: AsyncSession) -> None:
    user = await world.actor()
    body = (await user.get("/admin/method-settings")).json()
    assert body == {
        "large_leaf_hours": {"medium": "80.00", "detailed": "40.00"},
        "medium_expected_units": {"min": 5, "max": 15},
        "pm_percent_default": "18",
        "autoarchive_days": 180,
    }
    await db_session.merge(SystemSetting(key="method.pm_percent_default", value=12.5))
    leaf = {"medium": 60, "detailed": 30.5}
    await db_session.merge(SystemSetting(key="method.large_leaf_hours", value=leaf))
    await db_session.flush()
    body = (await user.get("/admin/method-settings")).json()
    assert body["pm_percent_default"] == "12.5"
    assert body["large_leaf_hours"] == {"medium": "60.00", "detailed": "30.50"}


def test_method_defaults_match_settings_schema() -> None:
    props = load_json("settings.schema.json")["properties"]
    for key, value in method.DEFAULTS.items():
        assert props[method.PREFIX + key]["default"] == value, key
