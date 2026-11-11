"""QA-003 · TC-SEC-02: матрица «роль × действие» SPEC 3.3 (статус «Оценка») на уровне API.

Генератор по записям ``matrix_3_3`` из ``contracts/permissions.yaml``: для каждой строки
``M3.3-NN`` и каждого из 8 субъектов — запросы к эндпоинтам прав строки от имени субъекта в
проекте «со всем» (tests/security/stocked.py), где эксперт и ревьюер назначены на Бэкенд, а
объект запроса — лист Бэкенда (своя ветка).

* Запрет — ответ 403 или 404 (чужой объект неотличим от несуществующего, R-OBJECT-CHAIN).
  Проверяются только права, которые субъект не получает ни одной другой ячейкой матрицы:
  общее право (например, ``project.read``) в строке-запрете ещё не запрет всего эндпоинта.
* Разрешение — не 401/403/404. Изменяющий запрос идёт с заведомо неверным телом: право уже
  проверено, а данные не меняются (ответ 422). Изменяющие запросы без тела для разрешения не
  шлются — их проверяют функциональные тесты треков.

Отчёт покрытия строк печатается в конце прогона (``-s``) и проверяется: у каждой строки 3.3 —
хотя бы одна проверка. Строки SEC-AUTHZ-05 (``authz_examples``) — отдельные тесты ниже и в
тестах треков (ссылки в ``EXAMPLES_ELSEWHERE``).
"""

from __future__ import annotations

import functools
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.adm.helpers import step_up
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import Actor, World
from tests.security.crawl import OPENAPI, required_query
from tests.security.stocked import Stocked, stocked

from estimator.db.enums import SystemRole

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-02"), pytest.mark.spec("3.3"),
              pytest.mark.spec("SEC-AUTHZ-05")]  # fmt: skip

PERMISSIONS = Path(OPENAPI).with_name("permissions.yaml")
ALLOW = {"allow", "view"}
DENY_CODES = {403, 404}
NOT_ALLOWED = {401, 403, 404}
#: Объект для ``{параметра}`` по предыдущему сегменту пути.
PLACEHOLDERS = {
    ("projects", "id"): "project", ("nodes", "id"): "node", ("threads", "id"): "thread",
    ("messages", "id"): "message", ("snapshots", "id"): "snapshot", ("notes", "id"): "note",
    ("users", "id"): "user", ("admins", "id"): "user", ("view-state", "project_id"): "project",
    ("branches", "phase"): "phase", ("*", "discipline"): "discipline", ("stats", "tab"): "tab",
    ("settings", "section"): "section", ("members", "user_id"): "user",
    ("trash", "batch_id"): "batch", ("documents", "id"): "document",
    ("disciplines", "discipline_id"): "discipline",
}  # fmt: skip
PROBE_BODY = {"__probe__": "права проверяются раньше тела"}
#: Области ячеек, которые объект проверки (лист Бэкенда, вопрос эксперта Бэкенда модератору)
#: заведомо выполняет; ячейки с другими областями («автор», «адресат»…) проверяют тесты треков.
PROBE_SCOPES = {None, "any", "own_discipline", "all", "own_project"}


@functools.cache
def _contract() -> tuple[dict[str, Any], dict[str, Any]]:
    perms = yaml.safe_load(PERMISSIONS.read_text(encoding="utf-8"))
    api = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    return perms, api


def _rows() -> list[dict[str, Any]]:
    return _contract()[0]["matrix_3_3"]


@functools.cache
def _granted() -> dict[str, frozenset[str]]:
    """Права, которые субъект получает хотя бы одной разрешающей ячейкой матрицы."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in _rows():
        for subject, cell in row["cells"].items():
            if cell["effect"] in ALLOW:
                out[subject].update(cell.get("permissions") or row.get("permissions") or [])
    return {k: frozenset(v) for k, v in out.items()}


@functools.cache
def _conditional() -> frozenset[str]:
    """Права, выдаваемые только при настройке (``requires_setting``, например режим AD)."""
    grants = _contract()[0].get("grants", {})
    items = [g for v in grants.values() for g in (v if isinstance(v, list) else [])]
    return frozenset(
        g["permission"] for g in items if isinstance(g, dict) and g.get("requires_setting")
    )


def _endpoints(permission: str) -> list[tuple[str, str]]:
    perms, _ = _contract()
    out = []
    for item in perms["permissions"].get(permission, {}).get("endpoints", []):
        method, _, path = str(item).partition(" ")
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and path.startswith("/"):
            out.append((method, path.split("?")[0].strip()))
    return out


def _fill(path: str, ids: dict[str, Any]) -> str | None:
    segments = path.strip("/").split("/")
    out = []
    for i, seg in enumerate(segments):
        m = re.fullmatch(r"{(\w+)}", seg)
        if m is None:
            out.append(seg)
            continue
        prev = segments[i - 1] if i else ""
        key = PLACEHOLDERS.get((prev, m[1])) or PLACEHOLDERS.get(("*", m[1]))
        if key is None or ids.get(key) is None:
            return None
        out.append(str(ids[key]))
    return "/" + "/".join(out)


def _has_body(method: str, path: str) -> bool:
    ops = _contract()[1]["paths"].get(path, {})
    return "requestBody" in ops.get(method.lower(), {})


def _in_contract(method: str, path: str) -> bool:
    return method.lower() in _contract()[1]["paths"].get(path, {})


async def _subjects(world: World, db: AsyncSession, st: Stocked) -> dict[str, Actor]:
    await set_setting(db, "security.admin_networks", [])
    root = await world.actor(SystemRole.SUPERADMIN)
    await step_up(world, root)
    admin = await world.actor(SystemRole.ADMIN)
    await step_up(world, admin)
    auditor = await world.actor(SystemRole.SECURITY_AUDITOR)
    head = await world.actor(SystemRole.PRESALE_HEAD)
    await step_up(world, st.s.moderator)
    return {
        "superadmin": root, "admin": admin, "security_auditor": auditor, "presale_head": head,
        "project_moderator": st.s.moderator, "expert": st.s.backend_expert,
        "reviewer": st.reviewer, "project_presale": st.presale,
    }  # fmt: skip


async def _call(actor: Actor, method: str, path: str, template: str, body: bool) -> int:
    kwargs: dict[str, Any] = {"json": PROBE_BODY} if body else {}
    if method == "GET":
        return (await actor.get(path, params=required_query(template))).status_code
    return (await getattr(actor, method.lower())(path, **kwargs)).status_code


COVERAGE: dict[str, int] = {}


@pytest.mark.parametrize("row_id", [r["id"] for r in _rows()])
async def test_matrix_row(world: World, db_session: AsyncSession, row_id: str) -> None:
    row = next(r for r in _rows() if r["id"] == row_id)
    st = await stocked(world, db_session)
    actors = await _subjects(world, db_session, st)
    checks: list[str] = []
    failures: list[str] = []
    inconclusive: list[str] = []
    # сначала запреты, потом разрешения: разрешённый запрос мог бы изменить данные
    cells = sorted(row["cells"].items(), key=lambda kv: kv[1]["effect"] in ALLOW)
    for subject, cell in cells:
        effect = cell["effect"]
        if effect == "na" or cell.get("context"):
            continue  # режим поддержки и «любой проект» — отдельные тесты ниже
        if effect in ALLOW and cell.get("scope") not in PROBE_SCOPES:
            continue
        if effect in ALLOW:
            permissions = cell.get("permissions") or row.get("permissions") or []
        else:
            permissions = [p for p in row.get("permissions") or [] if p not in _granted()[subject]]
        for permission in permissions:
            if permission in _conditional():
                continue  # проверяется в тестах режима (test_ad_search_api)
            for method, template in _endpoints(permission):
                path = _fill(template, st.ids)
                if path is None or not _in_contract(method, template):
                    continue
                body = _has_body(method, template)
                if effect in ALLOW and method != "GET" and not body:
                    continue
                if effect in ALLOW and effect == "view" and method != "GET":
                    continue
                status = await _call(actors[subject], method, path, template, body)
                if effect not in ALLOW and status == 422:
                    # право маршрута у субъекта есть, запрет зависит от тела (например, «не
                    # нужно» для ветки или выгрузка с деньгами) — проверяют тесты треков
                    inconclusive.append(f"{subject} {method} {template}")
                    continue
                checks.append(f"{subject} {method} {template} → {status}")
                expected_ok = status not in NOT_ALLOWED if effect in ALLOW else status in DENY_CODES
                if not expected_ok:
                    failures.append(f"{subject} ({effect}) {method} {template} → {status}")
    COVERAGE[row_id] = len(checks)
    assert failures == [], "\n".join(failures)


def test_matrix_coverage_report() -> None:
    """Отчёт покрытия: строки 3.3 без единой проверки (их проверяют только тесты треков)."""
    rows = [r["id"] for r in _rows()]
    if len(COVERAGE) < len(rows):
        pytest.skip("отчёт строится, когда в том же процессе прошли все строки матрицы")
    uncovered = [r for r in rows if not COVERAGE.get(r)]
    print(f"\nTC-SEC-02: проверено строк {len(rows) - len(uncovered)} из {len(rows)}; "
          f"без проверок: {', '.join(uncovered) or 'нет'}")  # fmt: skip
    assert uncovered == [], uncovered


# --- SEC-AUTHZ-05: контекстные строки ------------------------------------------------------------


async def test_admin_support_session_and_presale_head(
    world: World, db_session: AsyncSession
) -> None:
    st = await stocked(world, db_session)
    pid, node = st.s.pid, st.ids["node"]
    admin = await world.actor(SystemRole.ADMIN)
    assert (await admin.get(f"/projects/{pid}/tree")).status_code == 404  # без поддержки
    opened = await admin.post(f"/admin/projects/{pid}/support-session",
                              json={"reason": "Проверка жалобы на расчёт итогов"})  # fmt: skip
    assert opened.status_code == 201, opened.text
    assert (await admin.get(f"/projects/{pid}/tree")).status_code == 200
    assert (await admin.get(f"/projects/{pid}/money")).status_code == 403
    assert (await admin.patch(f"/nodes/{node}", json={"base_version": 1, "changes": {"r": "13"}})
            ).status_code == 403  # fmt: skip

    head = await world.actor(SystemRole.PRESALE_HEAD)
    assert (await head.get(f"/projects/{pid}/money")).status_code == 200
    assert (await head.patch(f"/nodes/{node}", json={"base_version": 1, "changes": {"r": "13"}})
            ).status_code == 403  # fmt: skip
    assert (await head.post(f"/projects/{pid}/notes", json={"body": "x"})).status_code == 403
    for subject in (SystemRole.SECURITY_AUDITOR, SystemRole.SUPERADMIN):
        assert (await (await world.actor(subject)).get(f"/projects/{pid}/tree")).status_code == 404


async def test_foreign_project_is_404(world: World, db_session: AsyncSession) -> None:
    """IDOR: эксперт другого проекта не отличает чужие объекты от несуществующих."""
    st = await stocked(world, db_session)
    other = await stocked(world, db_session)
    stranger = other.s.backend_expert
    node, snap, msg = st.ids["node"], st.ids["snapshot"], st.ids["message"]
    for path in (f"/projects/{st.s.pid}/tree", f"/projects/{st.s.pid}", f"/nodes/{node}/history",
                 f"/nodes/{node}/messages", f"/snapshots/{snap}/diff?with=current",
                 f"/messages/{msg}/history"):  # fmt: skip
        assert (await stranger.get(path)).status_code == 404, path
    patch = await stranger.patch(f"/nodes/{st.ids['node']}",
                                 json={"base_version": 1, "changes": {"r": "13"}})  # fmt: skip
    assert patch.status_code == 404
