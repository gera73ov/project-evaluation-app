"""Шифрование значений AES-256-GCM с идентификатором ключа (SEC-003; SEC-CRYPT-02, SEC-CRYPT-03).

Формат зашифрованного значения (``BYTEA`` в БД, base64 в ``system_settings``)::

    0x01 | длина id (1 байт) | id ключа (ASCII) | nonce (12 байт) | шифротекст и тег GCM (16 байт)

Дополнительные данные GCM (AAD) — заголовок (версия и id ключа) и *контекст* — где лежит
значение, например ``users.totp_secret_enc:<id пользователя>``. Поэтому шифротекст нельзя
незаметно подменить, перенести в другую строку или другой столбец: расшифровка падает
(:class:`DecryptionError`). Контексты всех зашифрованных столбцов — :mod:`.contexts`.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from estimator.security.crypto.keys import KeyRing, MasterKey

VERSION = 1
NONCE_BYTES = 12
TAG_BYTES = 16


class DecryptionError(ValueError):
    """Значение подменено, повреждено, зашифровано другим контекстом или неизвестным ключом."""


def _header(kid: str) -> bytes:
    raw = kid.encode("ascii")
    return bytes((VERSION, len(raw))) + raw


def _aad(header: bytes, context: str) -> bytes:
    return header + b"\x00" + context.encode("utf-8")


def encrypt_with(key: MasterKey, plaintext: bytes, context: str) -> bytes:
    """Зашифровать конкретным ключом (для ротации и тестов)."""
    header = _header(key.kid)
    nonce = os.urandom(NONCE_BYTES)
    return header + nonce + AESGCM(key.key).encrypt(nonce, plaintext, _aad(header, context))


def parse_header(blob: bytes) -> tuple[str, int]:
    """Вернуть идентификатор ключа и смещение nonce."""
    if len(blob) < 2 or blob[0] != VERSION:
        raise DecryptionError("неизвестный формат зашифрованного значения")
    end = 2 + blob[1]
    if blob[1] == 0 or len(blob) < end + NONCE_BYTES + TAG_BYTES:
        raise DecryptionError("зашифрованное значение повреждено")
    try:
        kid = blob[2:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise DecryptionError("зашифрованное значение повреждено") from exc
    return kid, end


def key_id(blob: bytes) -> str:
    """Каким ключом зашифровано значение (без расшифровки)."""
    return parse_header(bytes(blob))[0]


class Cipher:
    """Шифрование и расшифровка значений связкой ключей."""

    def __init__(self, keyring: KeyRing) -> None:
        self.keyring = keyring

    @property
    def current_kid(self) -> str:
        return self.keyring.current.kid

    def encrypt(self, plaintext: bytes, context: str) -> bytes:
        return encrypt_with(self.keyring.current, plaintext, context)

    def decrypt(self, blob: bytes, context: str) -> bytes:
        blob = bytes(blob)
        kid, end = parse_header(blob)
        key = self.keyring.get(kid)
        if key is None:
            raise DecryptionError(f"значение зашифровано неизвестным ключом {kid}")
        nonce = blob[end : end + NONCE_BYTES]
        try:
            return AESGCM(key.key).decrypt(
                nonce, blob[end + NONCE_BYTES :], _aad(blob[:end], context)
            )
        except InvalidTag as exc:
            raise DecryptionError("значение подменено или зашифровано для другого места") from exc

    def encrypt_text(self, text: str, context: str) -> bytes:
        return self.encrypt(text.encode("utf-8"), context)

    def decrypt_text(self, blob: bytes, context: str) -> str:
        return self.decrypt(blob, context).decode("utf-8")

    def needs_rotation(self, blob: bytes) -> bool:
        return key_id(blob) != self.current_kid

    def reencrypt(self, blob: bytes, context: str) -> bytes:
        """Перешифровать текущим ключом (ротация, SEC-CRYPT-02)."""
        return self.encrypt(self.decrypt(blob, context), context)

    # --- секретные ключи system_settings: {"enc": base64, "kid": id} (contracts/db/schema.md) ---

    def encrypt_setting(self, setting_key: str, value: Any) -> dict[str, str]:
        """Секрет настройки (``smtp.password``, ``auth.ad.bind_password``…) для ``value`` JSONB."""
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        blob = self.encrypt(raw, setting_context(setting_key))
        return {"enc": base64.b64encode(blob).decode("ascii"), "kid": self.current_kid}

    def decrypt_setting(self, setting_key: str, stored: dict[str, Any]) -> Any:
        blob = setting_blob(stored)
        return json.loads(self.decrypt(blob, setting_context(setting_key)))


def setting_context(setting_key: str) -> str:
    return f"system_settings:{setting_key}"


def is_encrypted_setting(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {"enc", "kid"}


def setting_blob(stored: dict[str, Any]) -> bytes:
    if not is_encrypted_setting(stored):
        raise DecryptionError("значение настройки не зашифровано")
    try:
        blob = base64.b64decode(stored["enc"], validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise DecryptionError("значение настройки повреждено") from exc
    if key_id(blob) != stored["kid"]:
        raise DecryptionError("идентификатор ключа настройки не совпадает с шифротекстом")
    return blob
