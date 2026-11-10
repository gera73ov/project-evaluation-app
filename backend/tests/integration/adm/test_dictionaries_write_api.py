"""ADM-007: запись справочников — правила 7.5, «было → стало» (BR-ADM-01), C-31, BR-TREE-08."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from tests.integration.core.conftest import Actor, World
from tests.integration.core.helpers import create_project

pytestmark = [pytest.mark.integration, pytest.mark.spec("7.5"), pytest.mark.spec("BR-ADM-01")]


async def _audit(db: AsyncSession, dictionary: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'dict.changed' "
            "AND details->>'dictionary' = :d ORDER BY id"
        ),
        {"d": dictionary},
    )
    return [r[0] for r in rows.all()]


def _code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json().get("code", "")


async def _items(actor: Actor, path: str) -> list[dict[str, Any]]:
    return (await actor.get(f"{path}?include_inactive=true")).json()["items"]


async def test_only_admin_writes(world: World) -> None:
    moderator = await world.actor(SystemRole.MODERATOR)
    response = await moderator.post("/admin/tags", json={"name": "X"})
    assert _code(response) == (403, "FORBIDDEN")


async def test_phases_cross_cutting_and_delete(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    created = await admin.post("/admin/phases", json={"name": " Пилот "})
    assert created.status_code == 201, created.text
    phase = created.json()
    assert (phase["name"], phase["is_cross_cutting"], phase["is_active"]) == ("Пилот", False, True)
    [entry] = await _audit(db_session, "phases")
    assert entry["op"] == "create"
    assert entry["changes"]["name"] == [None, "Пилот"]

    old = next(p for p in await _items(admin, "/admin/phases") if p["is_cross_cutting"])
    off = await admin.patch(f"/admin/phases/{old['id']}", json={"is_cross_cutting": False})
    assert _code(off) == (409, "DICTIONARY_IN_USE")
    moved = await admin.patch(f"/admin/phases/{phase['id']}", json={"is_cross_cutting": True})
    assert moved.status_code == 200, moved.text
    flags = {p["id"]: p["is_cross_cutting"] for p in await _items(admin, "/admin/phases")}
    assert sum(flags.values()) == 1
    assert flags[phase["id"]] is True
    assert _code(await admin.delete(f"/admin/phases/{phase['id']}")) == (409, "DICTIONARY_IN_USE")
    await admin.patch(f"/admin/phases/{old['id']}", json={"is_cross_cutting": True})

    # используемая фаза — только деактивация
    moderator = await world.actor(SystemRole.MODERATOR)
    await create_project(world, moderator, "Разработка")
    used = next(p for p in await _items(admin, "/admin/phases") if p["name"] == "Разработка")
    assert _code(await admin.delete(f"/admin/phases/{used['id']}")) == (409, "DICTIONARY_IN_USE")
    off = await admin.patch(f"/admin/phases/{used['id']}", json={"is_active": False})
    assert off.json()["is_active"] is False
    assert (await _audit(db_session, "phases"))[-1]["op"] == "deactivate"

    assert (await admin.delete(f"/admin/phases/{phase['id']}")).status_code == 409
    fresh = (await admin.post("/admin/phases", json={"name": "Временная"})).json()
    assert (await admin.delete(f"/admin/phases/{fresh['id']}")).status_code == 204
    assert (await _audit(db_session, "phases"))[-1]["op"] == "delete"
    assert (await admin.patch(f"/admin/phases/{fresh['id']}", json={})).status_code == 404


async def test_disciplines_and_profiles(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    body = {"name": "Безопасность", "short_name": "ИБ", "color": "#AA3300"}
    created = await admin.post("/admin/disciplines", json=body)
    assert created.status_code == 201, created.text
    discipline = created.json()
    assert discipline["default_profile_id"] is None
    dup = await admin.post("/admin/disciplines", json={**body, "name": "безопасность"})
    assert (dup.status_code, dup.json()["field"]) == (409, "name")
    missing = await admin.post("/admin/disciplines", json={"name": "Без цвета"})
    assert _code(missing) == (422, "VALIDATION_FAILED")

    types = await _items(admin, "/admin/node-types")
    work = next(t for t in types if t["is_system"])
    first = await admin.post(
        "/admin/profiles",
        json={"discipline_id": discipline["id"], "name": "Аудит", "type_chain": [work["id"]]},
    )
    assert first.status_code == 201, first.text
    profile = first.json()
    disciplines = {d["id"]: d for d in await _items(admin, "/admin/disciplines")}
    assert (
        disciplines[discipline["id"]]["default_profile_id"] == profile["id"]
    )  # первый — по умолчанию
    second = (
        await admin.post(
            "/admin/profiles",
            json={"discipline_id": discipline["id"], "name": "Пентест", "type_chain": [work["id"]]},
        )
    ).json()
    same = await admin.post(
        "/admin/profiles",
        json={"discipline_id": discipline["id"], "name": "аудит", "type_chain": [work["id"]]},
    )
    assert (same.status_code, same.json()["field"]) == (409, "name")
    alien = await admin.post(
        "/admin/profiles",
        json={"discipline_id": discipline["id"], "name": "Чужой", "type_chain": [discipline["id"]]},
    )
    assert _code(alien) == (422, "VALIDATION_FAILED")

    assert _code(await admin.delete(f"/admin/profiles/{profile['id']}")) == (
        409,
        "DICTIONARY_IN_USE",
    )
    switched = await admin.patch(
        f"/admin/disciplines/{discipline['id']}", json={"default_profile_id": second["id"]}
    )
    assert switched.json()["default_profile_id"] == second["id"]
    assert (await admin.delete(f"/admin/profiles/{profile['id']}")).status_code == 204
    other = next(d for d in disciplines.values() if d["id"] != discipline["id"])
    foreign = await admin.patch(
        f"/admin/disciplines/{other['id']}", json={"default_profile_id": second["id"]}
    )
    assert _code(foreign) == (422, "VALIDATION_FAILED")
    # дисциплина с профилями не удаляется; без них — удаляется
    assert (await admin.delete(f"/admin/disciplines/{discipline['id']}")).status_code == 409
    lone = (
        await admin.post(
            "/admin/disciplines", json={"name": "Пусто", "short_name": "П", "color": "#000000"}
        )
    ).json()
    assert (await admin.delete(f"/admin/disciplines/{lone['id']}")).status_code == 204
    ops = [e["op"] for e in await _audit(db_session, "profiles")]
    assert ops == ["create", "create", "delete"]


@pytest.mark.spec("BR-TREE-08")
async def test_node_types(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    types = await _items(admin, "/admin/node-types")
    work = next(t for t in types if t["is_system"])
    assert _code(await admin.delete(f"/admin/node-types/{work['id']}")) == (
        409,
        "DICTIONARY_IN_USE",
    )
    off = await admin.patch(f"/admin/node-types/{work['id']}", json={"is_active": False})
    assert _code(off) == (409, "DICTIONARY_IN_USE")

    norms = [{"label": "простой", "o": "1", "r": "2,5", "p": "4"}]
    created = await admin.post(
        "/admin/node-types", json={"name": "Выгрузка", "icon": "report", "norms": norms}
    )
    assert created.status_code == 201, created.text
    node_type = created.json()
    assert node_type["norms"] == [{"label": "простой", "o": "1", "r": "2.5", "p": "4"}]
    assert (node_type["is_system"], node_type["project_id"]) == (False, None)
    bad = [{"label": "x", "o": "5", "r": "2", "p": "4"}]
    wrong = await admin.patch(f"/admin/node-types/{node_type['id']}", json={"norms": bad})
    assert _code(wrong) == (422, "VALIDATION_FAILED")
    dup = await admin.post("/admin/node-types", json={"name": "выгрузка", "icon": "report"})
    assert _code(dup) == (409, "ALREADY_EXISTS")
    assert (await admin.delete(f"/admin/node-types/{node_type['id']}")).status_code == 204


async def test_ratios_tags_loss_reasons(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    a, b, *_ = await _items(admin, "/admin/disciplines")
    ratio_body = {"discipline_a_id": a["id"], "disciplines_b": [b["id"]], "min_pct": "10",
                  "max_pct": "35.5"}  # fmt: skip
    ratio = await admin.post("/admin/ratios", json=ratio_body)
    assert ratio.status_code == 201, ratio.text
    assert ratio.json()["max_pct"] == "35.5"
    self_ref = await admin.post("/admin/ratios", json={**ratio_body, "disciplines_b": [a["id"]]})
    assert _code(self_ref) == (422, "VALIDATION_FAILED")
    swapped = await admin.patch(f"/admin/ratios/{ratio.json()['id']}", json={"min_pct": "50"})
    assert _code(swapped) == (422, "VALIDATION_FAILED")
    assert (await admin.delete(f"/admin/ratios/{ratio.json()['id']}")).status_code == 204

    tag = await admin.post(
        "/admin/tags",
        json={"name": "Интеграция", "short_name": "ИНТ", "color": "#123456", "category": "risk"},
    )
    assert tag.status_code == 201, tag.text
    renamed = await admin.patch(f"/admin/tags/{tag.json()['id']}", json={"name": "Интеграции"})
    assert renamed.json()["name"] == "Интеграции"
    [_, update] = await _audit(db_session, "tags")
    assert update == {"op": "update", "dictionary": "tags",
                      "changes": {"name": ["Интеграция", "Интеграции"]}}  # fmt: skip
    assert (await admin.delete(f"/admin/tags/{tag.json()['id']}")).status_code == 204

    reason = await admin.post("/admin/loss-reasons", json={"name": "Цена"})
    assert (reason.status_code, reason.json()["is_other"]) == (201, False)
    assert (await admin.delete(f"/admin/loss-reasons/{reason.json()['id']}")).status_code == 204


async def test_currencies(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    assert _code(await admin.delete("/admin/currencies/RUB")) == (409, "DICTIONARY_IN_USE")
    off = await admin.patch("/admin/currencies/RUB", json={"is_active": False})
    assert _code(off) == (409, "DICTIONARY_IN_USE")
    created = await admin.post("/admin/currencies", json={"code": "AMD", "symbol": "֏"})
    assert created.status_code == 201, created.text
    again = await admin.post("/admin/currencies", json={"code": "AMD", "symbol": "֏"})
    assert (again.status_code, again.json()["field"]) == (409, "code")
    renamed = await admin.patch("/admin/currencies/AMD", json={"code": "AMX"})
    assert _code(renamed) == (422, "VALIDATION_FAILED")
    assert (await admin.patch("/admin/currencies/AMD", json={"symbol": "тг"})).json()[
        "symbol"
    ] == "тг"
    assert (await admin.delete("/admin/currencies/AMD")).status_code == 204
    assert (await admin.patch("/admin/currencies/XXX", json={})).status_code == 404


@pytest.mark.spec("C-31")
async def test_vat_rates_default_and_no_vat(world: World) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    rates = await _items(admin, "/admin/vat-rates")
    no_vat = next(r for r in rates if r["percent"] is None)
    default = next(r for r in rates if r["is_default"])
    assert _code(await admin.delete(f"/admin/vat-rates/{no_vat['id']}")) == (
        409,
        "DICTIONARY_IN_USE",
    )
    for body in ({"is_active": False}, {"percent": "5"}):
        response = await admin.patch(f"/admin/vat-rates/{no_vat['id']}", json=body)
        assert _code(response) == (409, "DICTIONARY_IN_USE"), body
    unset = await admin.patch(f"/admin/vat-rates/{default['id']}", json={"is_default": False})
    assert _code(unset) == (409, "DICTIONARY_IN_USE")
    assert _code(await admin.delete(f"/admin/vat-rates/{default['id']}")) == (
        409,
        "DICTIONARY_IN_USE",
    )
    second_no_vat = await admin.post(
        "/admin/vat-rates", json={"name": "Ещё без НДС", "percent": None}
    )
    assert _code(second_no_vat) == (422, "VALIDATION_FAILED")

    created = await admin.post(
        "/admin/vat-rates", json={"name": "НДС 5%", "percent": "5", "is_default": True}
    )
    assert created.status_code == 201, created.text
    defaults = [r["id"] for r in await _items(admin, "/admin/vat-rates") if r["is_default"]]
    assert defaults == [created.json()["id"]]
    back = await admin.patch(f"/admin/vat-rates/{default['id']}", json={"is_default": True})
    assert back.status_code == 200
    assert (await admin.delete(f"/admin/vat-rates/{created.json()['id']}")).status_code == 204
    over = await admin.post("/admin/vat-rates", json={"name": "Много", "percent": "120"})
    assert _code(over) == (422, "VALIDATION_FAILED")


async def test_put_method_settings(world: World, db_session: AsyncSession) -> None:
    admin = await world.actor(SystemRole.ADMIN)
    body = {
        "large_leaf_hours": {"medium": "60", "detailed": "30.5"},
        "medium_expected_units": {"min": 4, "max": 12},
        "pm_percent_default": "12,5",
        "autoarchive_days": 0,
    }
    saved = await admin.put("/admin/method-settings", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "large_leaf_hours": {"medium": "60.00", "detailed": "30.50"},
        "medium_expected_units": {"min": 4, "max": 12},
        "pm_percent_default": "12.5",
        "autoarchive_days": 0,
    }
    [entry] = await _audit(db_session, "method")
    assert entry["changes"]["pm_percent_default"] == [18, 12.5]
    assert entry["changes"]["autoarchive_days"] == [180, 0]
    stored = await db_session.scalar(
        text("SELECT value FROM system_settings WHERE key = 'method.large_leaf_hours'")
    )
    assert stored == {"medium": 60, "detailed": 30.5}

    # % УП по умолчанию — новым проектам
    moderator = await world.actor(SystemRole.MODERATOR)
    project_id = await create_project(world, moderator)
    project = (await moderator.get(f"/projects/{project_id}")).json()
    assert project["pm_percent"] == "12.5"

    for patch in (
        {"pm_percent_default": "12.3"},
        {"medium_expected_units": {"min": 9, "max": 3}},
        {"large_leaf_hours": {"medium": "0", "detailed": "1"}},
    ):
        response = await admin.put("/admin/method-settings", json={**body, **patch})
        assert _code(response) == (422, "VALIDATION_FAILED"), patch
    user = await world.actor()
    assert (await user.put("/admin/method-settings", json=body)).status_code == 403
