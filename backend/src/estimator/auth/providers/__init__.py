"""Провайдеры аутентификации (AUTH-001). Импорт пакета регистрирует ``local``."""

from estimator.auth.providers import local as _local  # noqa: F401  регистрация провайдера
from estimator.auth.providers.base import (
    LOCAL,
    AuthProvider,
    AuthResult,
    Credentials,
    Identity,
    ProviderNotAvailableError,
    authenticate,
    get_provider,
    provider_for_login,
    register_provider,
    registered_providers,
    unregister_provider,
)

__all__ = [
    "LOCAL",
    "AuthProvider",
    "AuthResult",
    "Credentials",
    "Identity",
    "ProviderNotAvailableError",
    "authenticate",
    "get_provider",
    "provider_for_login",
    "register_provider",
    "registered_providers",
    "unregister_provider",
]
