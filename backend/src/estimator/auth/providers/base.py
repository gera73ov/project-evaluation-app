"""Интерфейс провайдеров аутентификации и реестр (AUTH-001; ARCH-06, FR-AUTH-AD-11, Q-05).

Провайдер только проверяет учётные данные и возвращает :class:`Identity` — внешний
идентификатор и атрибуты — либо причину отказа из ``login_failure_reasons`` контракта аудита.
Сессии (AUTH-002), роли и аудит работают с результатом и о провайдерах не знают, поэтому
Kerberos/SPNEGO или OIDC добавляется новым классом и вызовом :func:`register_provider`.

Провайдер выбирается по ``auth.mode``; суперадминистратор всегда входит через ``local``
(FR-SA-01, раздел 7.2), в том числе в режиме AD.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import SystemRole
from estimator.db.models.users import User, UserRole
from estimator.security.audit.catalog import LOGIN_FAILURE_REASONS

LOCAL = "local"


@dataclass(frozen=True)
class Credentials:
    """Введённые логин и пароль; пароль не попадает в ``repr`` и логи."""

    login: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class Identity:
    """Кто вошёл: провайдер, внешний идентификатор, атрибуты и (если известна) учётка."""

    provider: str
    external_id: str
    login: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AuthResult:
    identity: Identity | None = None
    reason: str | None = None
    user_id: uuid.UUID | None = None  # известная учётка при отказе — для аудита

    def __post_init__(self) -> None:
        if (self.identity is None) == (self.reason is None):
            raise ValueError("нужно ровно одно из identity и reason")
        if self.reason is not None and self.reason not in LOGIN_FAILURE_REASONS:
            raise ValueError(f"причина отказа вне контракта аудита: {self.reason}")

    @property
    def ok(self) -> bool:
        return self.identity is not None

    @classmethod
    def success(cls, identity: Identity) -> AuthResult:
        return cls(identity=identity)

    @classmethod
    def failure(cls, reason: str, user_id: uuid.UUID | None = None) -> AuthResult:
        return cls(reason=reason, user_id=user_id)


class AuthProvider(ABC):
    """Провайдер: «проверить учётные данные → внешний идентификатор и атрибуты»."""

    name: ClassVar[str]

    @abstractmethod
    async def authenticate(self, session: AsyncSession, credentials: Credentials) -> AuthResult:
        """Проверить учётные данные. Не создаёт сессию и не пишет аудит."""


class ProviderNotAvailableError(LookupError):
    """Провайдер режима не зарегистрирован (например, ``ad`` до AUTH-013)."""


ProviderFactory = Callable[[], AuthProvider]
_registry: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    if name in _registry and not replace:
        raise ValueError(f"провайдер {name} уже зарегистрирован")
    _registry[name] = factory


def unregister_provider(name: str) -> None:
    _registry.pop(name, None)


def registered_providers() -> frozenset[str]:
    return frozenset(_registry)


def get_provider(name: str) -> AuthProvider:
    factory = _registry.get(name)
    if factory is None:
        raise ProviderNotAvailableError(name)
    return factory()


async def is_local_superadmin(session: AsyncSession, login: str) -> bool:
    """Логин принадлежит суперадминистратору (он всегда входит через ``local``)."""
    query = select(
        exists().where(
            func.lower(User.login) == login.strip().lower(),
            UserRole.user_id == User.id,
            UserRole.role == SystemRole.SUPERADMIN,
        )
    )
    return bool(await session.scalar(query))


async def provider_for_login(session: AsyncSession, mode: str, login: str) -> AuthProvider:
    """Провайдер для входа: по ``auth.mode``, для суперадминистратора — ``local``."""
    if mode != LOCAL and login and await is_local_superadmin(session, login):
        return get_provider(LOCAL)
    return get_provider(mode)


async def authenticate(session: AsyncSession, mode: str, credentials: Credentials) -> AuthResult:
    """Проверить вход в режиме ``mode`` (пустые поля отклоняются до провайдера)."""
    if not credentials.login.strip() or not credentials.password:
        return AuthResult.failure("empty_credentials")
    provider = await provider_for_login(session, mode, credentials.login)
    return await provider.authenticate(session, credentials)
