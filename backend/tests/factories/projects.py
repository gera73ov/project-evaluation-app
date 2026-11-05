"""Фабрика проекта «Портал дилеров» (SPEC 5.1, 6.5, 11; 17.4).

Дерево, фазы, дисциплины и деньги берутся из эталонной фикстуры расчёта CORE-001
(``contracts/fixtures/calc/portal-dilerov.json``), чтобы тестовые данные и эталон не расходились.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from tests.factories.base import stable_uuid

ROOT = Path(__file__).resolve().parents[3]
CALC_FIXTURE = ROOT / "contracts" / "fixtures" / "calc" / "portal-dilerov.json"

#: Команда проекта на макетах SPEC 11.5 и 11.8: логин → (роль, дисциплина или None).
PORTAL_TEAM: dict[str, tuple[str, str | None]] = {
    "a.smirnova": ("moderator", None),
    "p.sidorov": ("presale", None),
    "o.kuznetsova": ("expert", "d-analytics"),
    "d.morozov": ("expert", "d-arch"),
    "i.ivanov": ("expert", "d-backend"),
    "p.petrov": ("expert", "d-frontend"),
    "m.orlova": ("expert", "d-qa"),
}


@dataclass(frozen=True)
class ProjectData:
    title: str
    customer: str
    status: str
    calc_input: dict[str, Any]
    team: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    id: uuid.UUID = field(default=uuid.UUID(int=0))

    def __post_init__(self) -> None:
        if self.id.int == 0:
            object.__setattr__(self, "id", stable_uuid("project", self.title))

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return list(self.calc_input["nodes"])

    @property
    def leaves(self) -> list[dict[str, Any]]:
        parents = {n["parent_id"] for n in self.nodes}
        return [n for n in self.nodes if n["kind"] == "item" and n["id"] not in parents]

    def node_uuid(self, fixture_id: str) -> uuid.UUID:
        """UUID узла по его ID в фикстуре (``n-auth`` → UUID «Авторизации»)."""
        return stable_uuid("node", str(self.id), fixture_id)

    def experts_of(self, discipline_id: str) -> list[str]:
        return [
            login
            for login, (role, disc) in self.team.items()
            if role == "expert" and disc == discipline_id
        ]


@lru_cache
def _calc_fixture() -> dict[str, Any]:
    return json.loads(CALC_FIXTURE.read_text(encoding="utf-8"))


def portal_dilerov(status: str = "estimation") -> ProjectData:
    """Проект «Портал дилеров» в статусе ``status`` (по умолчанию «Оценка»)."""
    return ProjectData(
        title="Портал дилеров",
        customer="ООО «Пример»",
        status=status,
        calc_input=_calc_fixture()["input"],
        team=dict(PORTAL_TEAM),
    )
