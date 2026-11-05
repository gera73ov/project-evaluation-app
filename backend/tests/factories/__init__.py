"""QA-001 · фабрики тестовых данных.

Фабрики строят данные в памяти (dataclass) с детерминированными UUID, поэтому годятся и для
unit-тестов, и для заполнения БД: когда появятся модели (DB-003…DB-006), трек-владелец
добавляет функцию ``persist`` рядом с фабрикой, а сами данные не меняются.

* :mod:`.users` — пользователи и персонажи SPEC (И. Иванов, А. Смирнова, П. Сидоров…);
* :mod:`.projects` — проект «Портал дилеров» (SPEC 5.1, 6.5) из ``contracts/fixtures/calc``.
"""

from tests.factories.base import Sequence, stable_uuid
from tests.factories.projects import ProjectData, portal_dilerov
from tests.factories.users import PERSONAS, UserData, make_user, persona

__all__ = [
    "PERSONAS",
    "ProjectData",
    "Sequence",
    "UserData",
    "make_user",
    "persona",
    "portal_dilerov",
    "stable_uuid",
]
