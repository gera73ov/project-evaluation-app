"""Мастер-ключи шифрования (SEC-003; SEC-CRYPT-01, SEC-CRYPT-02, SEC-CRYPT-07).

Ключ приходит из переменной окружения или файла Docker secret ``encryption_key`` в виде
``<id>:<base64url 32 байта>``. Идентификатор ключа записывается в каждое зашифрованное
значение (SEC-CRYPT-02), поэтому при ротации старые значения читаются прежним ключом из
``ENCRYPTION_KEYS_OLD``, а ``estimator rotate-key`` перешифровывает их текущим.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import SecretStr

from estimator.config import Settings

KEY_BYTES = 32  # AES-256 (SEC-CRYPT-01: ключ 256 бит)
_KID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class KeyConfigError(ValueError):
    """Ключ не задан или задан неверно. Текст ошибки не содержит значения ключа."""


@dataclass(frozen=True)
class MasterKey:
    """Мастер-ключ с идентификатором. ``repr`` не показывает ключ."""

    kid: str
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not _KID_RE.fullmatch(self.kid):
            raise KeyConfigError("идентификатор ключа: латиница, цифры, «-» и «_», до 32 символов")
        if len(self.key) != KEY_BYTES:
            raise KeyConfigError(f"ключ {self.kid}: нужно ровно {KEY_BYTES} байта (256 бит)")


def parse_key(text: str) -> MasterKey:
    """Разобрать ``<id>:<base64url>``."""
    kid, sep, encoded = text.strip().partition(":")
    if not sep or not kid or not encoded:
        raise KeyConfigError("формат ключа: <id>:<base64url 32 байта>")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError) as exc:
        raise KeyConfigError(f"ключ {kid}: значение не base64url") from exc
    return MasterKey(kid, raw)


def format_key(key: MasterKey) -> str:
    """Обратное к :func:`parse_key`."""
    return f"{key.kid}:{base64.urlsafe_b64encode(key.key).decode().rstrip('=')}"


def generate_key(kid: str | None = None) -> MasterKey:
    """Новый случайный ключ; идентификатор по умолчанию — дата: ``k20261105``."""
    return MasterKey(kid or datetime.now(UTC).strftime("k%Y%m%d"), secrets.token_bytes(KEY_BYTES))


@dataclass(frozen=True)
class KeyRing:
    """Текущий ключ (им шифруется всё новое) и прежние (только чтение, на время ротации)."""

    current: MasterKey
    old: tuple[MasterKey, ...] = ()

    def __post_init__(self) -> None:
        kids = [self.current.kid, *(k.kid for k in self.old)]
        if len(set(kids)) != len(kids):
            raise KeyConfigError("идентификаторы ключей повторяются")

    def get(self, kid: str) -> MasterKey | None:
        if kid == self.current.kid:
            return self.current
        return next((k for k in self.old if k.kid == kid), None)

    @property
    def kids(self) -> tuple[str, ...]:
        return (self.current.kid, *(k.kid for k in self.old))


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value().strip() if value is not None else ""


def keyring_from_settings(settings: Settings) -> KeyRing:
    """Собрать связку ключей из ``ENCRYPTION_KEY`` и ``ENCRYPTION_KEYS_OLD``."""
    current = _secret(settings.encryption_key)
    if not current:
        raise KeyConfigError(
            "не задан ENCRYPTION_KEY (Docker secret encryption_key); новый ключ — "
            "estimator generate-key"
        )
    old = [parse_key(part) for part in _secret(settings.encryption_keys_old).split(",") if part]
    return KeyRing(parse_key(current), tuple(old))
