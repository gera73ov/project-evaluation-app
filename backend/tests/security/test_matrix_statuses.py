"""QA-004 · TC-SEC-06: права по статусам проекта (SPEC 3.4, 4.2) на уровне API.

Генератор по записям ``matrix_3_4`` из ``contracts/permissions.yaml``: для каждой строки
``M3.4-NN`` и каждого из 5 статусов проект «со всем» (tests/security/stocked.py) переводится в этот
статус, и субъекты строки шлют запросы к эндпоинтам её прав.

* Роль задаёт матрица 3.3: проверяются только права, которые субъект получает в статусе «Оценка»
  (test_matrix_roles.py) с областью, которую объект проверки выполняет, — тогда разница ответов
  объясняется только статусом.
* Запрет статуса — 409 ``PROJECT_STATUS_CONFLICT`` или 403/404 (в «Подготовке» команда проект не
  видит). 422 на запрет — право маршрута проверено раньше статуса тела, вывод не сделать.
* Разрешение — не 401/403/404 и не 409 ``PROJECT_STATUS_CONFLICT``. Изменяющий запрос идёт с
  заведомо неверным телом; без тела для разрешения не шлётся.
* Если ячейка разрешает только части субъектов (``subjects``), остальным из ``applies_to`` —
  запрет.
* Толкование: в «Подготовке» проект видят только модераторы (строка «Проект виден»), поэтому
  ✅ строк «Статусы вопросов заказчику» и «Результат пресейла» в «Подготовке» относятся к тем, кто
  проект видит; остальной команде — 404, как у невидимого проекта.
* «Копировать ветку из проекта» (M3.4-09) — про проект-источник: отдельный тест ниже, приёмник
  в «Оценке».

Строки уведомлений (M3.4-15, M3.4-16) прав-эндпоинтов не имеют: их проверяют тесты NTF
(``EXAMPLES_ELSEWHERE``).
"""

from __future__ import annotations

import functools
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.core.conftest import Actor, World
from tests.security.crawl import required_query
from tests.security.stocked import Stocked, stocked
from tests.security.test_matrix_roles import (
    ALLOW,
    PROBE_BODY,
    PROBE_SCOPES,
    _conditional,
    _contract,
    _endpoints,
    _fill,
    _has_body,
    _in_contract,
    _subjects,
)

from estimator.db.enums import ProjectStatus
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node

pytestmark = [pytest.mark.integration, pytest.mark.tc("TC-SEC-06"), pytest.mark.spec("3.4"),
              pytest.mark.spec("4.2"), pytest.mark.spec("BR-PRJ-01")]  # fmt: skip

STATUSES = [s.value for s in ProjectStatus]
CONFLICT = "PROJECT_STATUS_CONFLICT"
#: Строки без эндпоинтов прав → где они проверены.
EXAMPLES_ELSEWHERE = {
    "M3.4-15": "tests/integration/ntf (оценочные письма только в «Оценке» и «Сведении»)",
    "M3.4-16": "tests/integration/ntf (служебные письма в любом статусе)",
}
#: Строки, которые проверяет отдельный тест.
OWN_TESTS = {"M3.4-09"}
#: Путь из «Оценки» в статус по стрелкам 4.2.
ROUTE = {
    "estimation": [],
    "consolidation": ["consolidation"],
    "completed": ["consolidation", "completed"],
    "archived": ["consolidation", "completed", "archived"],
}


def _rows() -> list[dict[str, Any]]:
    return _contract()[0]["matrix_3_4"]


def _expand(subjects: list[str]) -> list[str]:
    groups = _contract()[0]["subject_groups"]
    out: list[str] = []
    for s in subjects:
        out += [x for x in groups.get(s, [s]) if x not in out]
    return out


@functools.cache
def _probeable() -> dict[str, frozenset[str]]:
    """Права субъекта в «Оценке» (3.3) с областью, которую объект проверки выполняет."""
    out: dict[str, set[str]] = {}
    for row in _contract()[0]["matrix_3_3"]:
        for subject, cell in row["cells"].items():
            if cell["effect"] in ALLOW and cell.get("scope") in PROBE_SCOPES:
                perms = cell.get("permissions") or row.get("permissions") or []
                out.setdefault(subject, set()).update(perms)
    return {k: frozenset(v) for k, v in out.items()}


async def _to_status(st: Stocked, db: AsyncSession, status: str) -> None:
    if status == "preparation":
        project = await db.get(Project, st.s.pid)
        assert project is not None
        project.status = ProjectStatus.PREPARATION
        await db.flush()
        return
    for to in ROUTE[status]:
        moved = await st.s.moderator.post(f"/projects/{st.s.pid}/status", json={"to": to})
        assert moved.status_code == 200, moved.text


async def _call(actor: Actor, method: str, path: str, template: str, body: bool) -> tuple[int, str]:
    kwargs: dict[str, Any] = {"json": PROBE_BODY} if body else {}
    if method == "GET":
        response = await actor.get(path, params=required_query(template))
    else:
        response = await getattr(actor, method.lower())(path, **kwargs)
    code = ""
    if response.status_code >= 400 and "json" in response.headers.get("content-type", ""):
        code = response.json().get("code", "")
    return response.status_code, code


def _cases() -> list[tuple[str, str]]:
    return [(r["id"], s) for r in _rows() for s in STATUSES
            if r.get("permissions") and r["id"] not in OWN_TESTS]  # fmt: skip


@functools.cache
def _visible_in_preparation() -> frozenset[str]:
    row = next(r for r in _rows() if r["key"] == "project.visibility")
    return frozenset(_expand(row["statuses"]["preparation"]["subjects"]))


COVERAGE: dict[str, int] = {}


@pytest.mark.parametrize(("row_id", "status"), _cases())
async def test_matrix_status(
    world: World, db_session: AsyncSession, row_id: str, status: str
) -> None:
    row = next(r for r in _rows() if r["id"] == row_id)
    cell = row["statuses"][status]
    st = await stocked(world, db_session)
    actors = await _subjects(world, db_session, st)
    await _to_status(st, db_session, status)
    everyone = _expand(row.get("applies_to") or [])
    allowed = _expand(cell["subjects"]) if cell.get("subjects") else everyone
    members = set(_expand(["project_member"]))
    hidden = set() if status != "preparation" else members - _visible_in_preparation()
    plan = [(s, cell["effect"] in ALLOW and s in allowed and s not in hidden) for s in everyone]
    plan.sort(key=lambda p: p[1])  # сначала запреты: разрешённый запрос мог бы изменить данные
    checks: list[str] = []
    failures: list[str] = []
    for subject, allow in plan:
        for permission in row["permissions"]:
            if permission not in _probeable().get(subject, ()) or permission in _conditional():
                continue
            for method, template in _endpoints(permission):
                path = _fill(template, st.ids)
                if path is None or not _in_contract(method, template):
                    continue
                body = _has_body(method, template)
                if allow and method != "GET" and not body:
                    continue
                status_code, code = await _call(actors[subject], method, path, template, body)
                if not allow and status_code == 422:
                    continue
                checks.append(f"{subject} {method} {template} → {status_code} {code}")
                if allow:
                    ok = status_code not in {401, 403, 404} and code != CONFLICT
                else:
                    ok = status_code in {403, 404} or (status_code, code) == (409, CONFLICT)
                if not ok:
                    effect = "allow" if allow else "deny"
                    failures.append(
                        f"{subject} ({effect}, {status}) {method} {template} → {status_code} {code}"
                    )
    COVERAGE[f"{row_id}:{status}"] = len(checks)
    assert failures == [], "\n".join(failures)


def test_matrix_status_coverage_report() -> None:
    """Отчёт покрытия: строки 3.4, у которых ни в одном статусе нет проверки API."""
    if len(COVERAGE) < len(_cases()):
        pytest.skip("отчёт строится, когда в том же процессе прошли все ячейки матрицы 3.4")
    rows = [r["id"] for r in _rows()]
    uncovered = [r for r in rows if r not in EXAMPLES_ELSEWHERE and r not in OWN_TESTS
                 and not any(v for k, v in COVERAGE.items() if k.startswith(f"{r}:"))]  # fmt: skip
    print(f"\nTC-SEC-06: проверено строк {len(rows) - len(uncovered)} из {len(rows)}; "
          f"без проверок API: {', '.join(uncovered) or 'нет'}")  # fmt: skip
    assert uncovered == [], uncovered


@pytest.mark.parametrize("status", STATUSES)
async def test_copy_branch_source_status(
    world: World, db_session: AsyncSession, status: str
) -> None:
    """M3.4-09: ветку можно взять из проекта в любом статусе, кроме «Подготовки»."""
    st = await stocked(world, db_session)
    s = st.s
    source = await s.branch(db_session, s.backend)
    copied = await s.moderator.post(f"/projects/{s.pid}/copy", json={"name": "Приёмник"})
    assert copied.status_code == 201, copied.text
    target_pid = copied.json()["project"]["id"]
    launched = await s.moderator.post(f"/projects/{target_pid}/status", json={"to": "estimation"})
    assert launched.status_code == 200, launched.text
    target = (await db_session.scalars(
        select(Node).where(Node.project_id == uuid.UUID(target_pid),
                           Node.discipline_id == s.backend, Node.kind == "discipline")
        .order_by(Node.position)
    )).first()  # fmt: skip
    assert target is not None
    await _to_status(st, db_session, status)
    response = await s.backend_expert.post(
        f"/nodes/{target.id}/copy-from", json={"source_node_id": str(source.id)}
    )
    if row_allows(status):
        assert response.status_code == 201, (status, response.text)
    else:
        assert response.status_code in {403, 404, 409}, (status, response.text)


def row_allows(status: str) -> bool:
    row = next(r for r in _rows() if r["id"] == "M3.4-09")
    return row["statuses"][status]["effect"] in ALLOW
