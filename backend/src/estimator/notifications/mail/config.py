"""Параметры SMTP из ``system_settings`` (NTF-002; ключи ``smtp.server``, ``smtp.password``).

Пароль хранится зашифрованным (SEC-CRYPT-03) и расшифровывается только перед отправкой.
``host = null`` — SMTP не настроен: письма не отправляются, ссылки установки пароля
выдаются на экран (FR-AUTH-LOC-01).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from estimator.security.crypto import Cipher
from estimator.security.crypto.aead import is_encrypted_setting

#: Значение ``smtp.server`` по умолчанию (contracts/settings.schema.json).
DEFAULT_SERVER: dict[str, Any] = {
    "host": None,
    "port": 587,
    "security": "starttls",
    "username": None,
    "from_address": None,
    "from_name": "Оценка проектов",
    "timeout_seconds": 10,
}


@dataclass(frozen=True)
class SmtpConfig:
    host: str | None
    port: int = 587
    security: str = "starttls"  # starttls | tls | none
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    from_address: str | None = None
    from_name: str = "Оценка проектов"
    timeout_seconds: int = 10

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)

    @classmethod
    def from_settings(
        cls,
        server: Mapping[str, Any] | None,
        password: Mapping[str, Any] | str | None,
        cipher: Cipher | None = None,
    ) -> SmtpConfig:
        """Собрать из значений ``smtp.server`` и ``smtp.password`` (зашифрованного или открытого).

        Открытый пароль приходит только из формы мастера настройки (проверка до сохранения).
        """
        values = {**DEFAULT_SERVER, **(server or {})}
        if is_encrypted_setting(password):
            if cipher is None:
                raise ValueError("для зашифрованного пароля SMTP нужен шифратор")
            secret = cipher.decrypt_setting("smtp.password", password)  # type: ignore[arg-type]
        else:
            secret = password if isinstance(password, str) else None
        return cls(
            host=values["host"],
            port=int(values["port"]),
            security=values["security"],
            username=values["username"],
            password=secret,
            from_address=values["from_address"],
            from_name=values["from_name"],
            timeout_seconds=int(values["timeout_seconds"]),
        )


async def load_smtp_settings(conn: AsyncConnection) -> tuple[dict[str, Any] | None, Any]:
    """Прочитать ``smtp.server`` и ``smtp.password`` (как хранятся, пароль не расшифровывается)."""
    rows = await conn.execute(
        text("SELECT key, value FROM system_settings WHERE key IN ('smtp.server', 'smtp.password')")
    )
    values = dict(rows.all())
    return values.get("smtp.server"), values.get("smtp.password")
