"""Фабрика пользователей (SPEC 3.1, 14.2 ``users``, ``user_roles``; 17.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from tests.factories.base import Sequence, stable_uuid

#: Системные роли из contracts/permissions.yaml (``user`` есть у всех и не хранится).
SYSTEM_ROLES = frozenset(
    {"superadmin", "admin", "moderator", "presale", "presale_head", "security_auditor"}
)

_logins = Sequence("user{}")


@dataclass(frozen=True)
class UserData:
    login: str
    full_name: str
    roles: frozenset[str] = frozenset()
    email: str | None = None
    status: str = "active"  # active | blocked (14.2 users.status)
    block_reason: str | None = None
    source: str = "local"  # local | ad
    timezone: str = "Europe/Moscow"
    totp_enabled: bool = False
    id: uuid.UUID = field(default=uuid.UUID(int=0))

    def __post_init__(self) -> None:
        unknown = self.roles - SYSTEM_ROLES
        if unknown:
            raise ValueError(f"неизвестные системные роли: {sorted(unknown)}")
        if self.id.int == 0:
            object.__setattr__(self, "id", stable_uuid("user", self.login))


def make_user(**overrides: object) -> UserData:
    """Новый пользователь с уникальным логином; поля переопределяются аргументами."""
    login = str(overrides.pop("login", next(_logins)))
    defaults: dict[str, object] = {
        "full_name": f"Тестовый {login}",
        "email": f"{login}@example.test",
    }
    return UserData(login=login, **{**defaults, **overrides})  # type: ignore[arg-type]


#: Персонажи макетов SPEC 11 и сценариев 17.2 (роли в проекте — в :mod:`.projects`).
PERSONAS: dict[str, UserData] = {
    u.login: u
    for u in (
        UserData("superadmin", "Суперадминистратор", frozenset({"superadmin"}), totp_enabled=True),
        UserData("v.kozlov", "В. Козлов", frozenset({"admin"}), totp_enabled=True),
        UserData("l.frolova", "Л. Фролова", frozenset({"security_auditor"})),
        UserData("e.sokolova", "Е. Соколова", frozenset({"presale_head"}), totp_enabled=True),
        UserData("a.smirnova", "А. Смирнова", frozenset({"moderator"}), totp_enabled=True),
        UserData("i.ivanov", "И. Иванов", frozenset({"moderator"})),
        UserData("p.sidorov", "П. Сидоров", frozenset({"presale"}), totp_enabled=True),
        UserData("o.kuznetsova", "О. Кузнецова"),
        UserData("d.morozov", "Д. Морозов"),
        UserData("p.petrov", "П. Петров"),
        UserData("m.orlova", "М. Орлова"),
        UserData("n.novikov", "Н. Новиков", status="blocked", block_reason="manual"),
    )
}


def persona(login: str, **overrides: object) -> UserData:
    """Персонаж SPEC с необязательными изменениями: ``persona("i.ivanov", status="blocked")``."""
    return replace(PERSONAS[login], **overrides)  # type: ignore[arg-type]
