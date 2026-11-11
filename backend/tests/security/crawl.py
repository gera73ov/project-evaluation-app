"""QA-005, QA-007 · обход всех GET-эндпоинтов контракта от имени пользователя.

Список маршрутов — из ``contracts/openapi.yaml`` (реестр маршрутов, API-004): новый эндпоинт
попадает в проверки TC-SEC-03 и TC-SEC-07 сам. Параметры пути подставляются из известных
объектов сценария; маршруты с файлами (скачивание, выгрузки) и мастер настройки пропускаются —
файлы проверяет TC-SEC-04 (QA-006).
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from tests.integration.core.conftest import Actor

OPENAPI = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
SKIP = re.compile(r"/download$|/export$|^/ws$|^/system/setup/|^/api/")
#: Первая часть пути → ключ объекта сценария для ``{id}``.
OWNERS = {
    "projects": "project", "nodes": "node", "messages": "message", "snapshots": "snapshot",
    "documents": "document", "exports": "export", "admin": "user", "me": "project",
}  # fmt: skip
NAMED = {"project_id": "project", "section": "section", "tab": "tab"}
#: Обязательные параметры запроса GET-маршрутов контракта.
QUERY = {
    "q": "Тест",
    "from": "2026-01-01",
    "to": "2026-12-31",
    "since": 0,
    "with": "current",
    "format": "xlsx",
}


def required_query(template: str) -> dict[str, Any]:
    spec = _spec()
    shared = spec.get("components", {}).get("parameters", {})
    params = []
    for prm in spec["paths"][template]["get"].get("parameters", []):
        if "$ref" in prm:
            prm = shared[prm["$ref"].rsplit("/", 1)[-1]]
        params.append(prm)
    return {
        p["name"]: QUERY[p["name"]] for p in params if p.get("in") == "query" and p.get("required")
    }


@functools.cache
def _spec() -> dict[str, Any]:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


def get_paths() -> list[str]:
    spec = _spec()
    return sorted(p for p, ops in spec["paths"].items() if "get" in ops and not SKIP.search(p))


def fill(path: str, ids: Mapping[str, Any]) -> str | None:
    """Путь с подставленными параметрами или ``None``, если объекта нет."""
    owner = OWNERS.get(path.strip("/").split("/")[0])
    out = path
    for name in re.findall(r"{(\w+)}", path):
        key = NAMED.get(name) or owner
        value = ids.get(key or "")
        if value is None:
            return None
        out = out.replace("{" + name + "}", str(value))
    return out


@dataclass
class Crawl:
    bodies: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)


async def crawl(actor: Actor, ids: Mapping[str, Any]) -> Crawl:
    """Обойти все GET-маршруты; JSON-ответы 2xx — в ``bodies``."""
    out = Crawl()
    for template in get_paths():
        path = fill(template, ids)
        if path is None:
            continue
        response = await actor.get(path, params=required_query(template))
        out.statuses[template] = response.status_code
        if response.is_success and "json" in response.headers.get("content-type", ""):
            out.bodies[template] = response.json()
    return out


def find(value: Any, key_test: Any, text_test: Any = None, path: str = "$") -> list[str]:
    """Пути ключей (``key_test(key, value)``) и строк (``text_test(value)``) во вложенном JSON."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key_test(str(key), item):
                found.append(f"{path}.{key}")
            found += find(item, key_test, text_test, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += find(item, key_test, text_test, f"{path}[{i}]")
    elif isinstance(value, str) and text_test is not None and text_test(value):
        found.append(path)
    return found
