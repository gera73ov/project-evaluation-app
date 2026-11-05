"""Криптосервис (SEC-003): AES-256-GCM с идентификатором ключа, envelope для документов, ротация.

Получить шифратор процесса: :func:`get_cipher` (ключи из ``ENCRYPTION_KEY`` и
``ENCRYPTION_KEYS_OLD``). Контексты столбцов — :mod:`estimator.security.crypto.contexts`.
"""

from __future__ import annotations

from functools import lru_cache

from estimator.config import get_settings
from estimator.security.crypto.aead import Cipher, DecryptionError, key_id
from estimator.security.crypto.keys import KeyConfigError, KeyRing, keyring_from_settings

__all__ = [
    "Cipher",
    "DecryptionError",
    "KeyConfigError",
    "KeyRing",
    "get_cipher",
    "key_id",
    "keyring_from_settings",
]


@lru_cache
def get_cipher() -> Cipher:
    """Шифратор процесса (ключи читаются один раз; смена ключа — перезапуск сервиса)."""
    return Cipher(keyring_from_settings(get_settings()))
