"""Перешифровка значений новым мастер-ключом (SEC-003; SEC-CRYPT-02, SPEC 18.4).

Порядок ротации (служба эксплуатации, ``manuals/``):

1. ``estimator generate-key`` → новый ключ; запечатанная копия — в сейф ИБ (SEC-CRYPT-07).
2. ``ENCRYPTION_KEY`` = новый ключ, ``ENCRYPTION_KEYS_OLD`` = прежний; перезапуск сервисов.
   С этого момента новое шифруется новым ключом, старое читается прежним.
3. ``estimator rotate-key`` — перешифровать всё, что зашифровано не текущим ключом.
4. ``estimator rotate-key --check`` → 0 значений на старых ключах; убрать ``ENCRYPTION_KEYS_OLD``.

Перешифровываются: ``users.totp_secret_enc``, секретные ключи ``system_settings``
(``{"enc", "kid"}``), ``customer_documents.key_enc``. Строка обновляется условием «значение
не изменилось с момента чтения», поэтому параллельная запись приложения не теряется: такая
строка уже зашифрована текущим ключом.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from estimator.security.crypto import contexts
from estimator.security.crypto.aead import (
    Cipher,
    DecryptionError,
    is_encrypted_setting,
    key_id,
    setting_blob,
)


@dataclass(frozen=True)
class Target:
    """Зашифрованный столбец. ``context`` строит AAD по ключу строки."""

    name: str
    select_sql: str
    update_sql: str
    context: Callable[[Any], str]
    is_setting: bool = False


TARGETS: tuple[Target, ...] = (
    Target(
        name="users.totp_secret_enc",
        select_sql="SELECT id, totp_secret_enc FROM users WHERE totp_secret_enc IS NOT NULL",
        update_sql=(
            "UPDATE users SET totp_secret_enc = :new WHERE id = :id AND totp_secret_enc = :old"
        ),
        context=contexts.totp_secret,
    ),
    Target(
        name="system_settings",
        select_sql="SELECT key, value FROM system_settings WHERE value ? 'enc'",
        update_sql=(
            "UPDATE system_settings SET value = CAST(:new AS jsonb) "
            "WHERE key = :id AND value = CAST(:old AS jsonb)"
        ),
        context=contexts.setting_context,
        is_setting=True,
    ),
    Target(
        name="customer_documents.key_enc",
        select_sql="SELECT id, key_enc FROM customer_documents",
        update_sql="UPDATE customer_documents SET key_enc = :new WHERE id = :id AND key_enc = :old",
        context=contexts.document_key,
    ),
)


@dataclass
class TargetReport:
    total: int = 0
    on_old_keys: int = 0
    reencrypted: int = 0
    changed_concurrently: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class RotationReport:
    current_kid: str
    targets: dict[str, TargetReport] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return sum(t.on_old_keys - t.reencrypted for t in self.targets.values())

    @property
    def errors(self) -> list[str]:
        return [e for t in self.targets.values() for e in t.errors]


def _blob(target: Target, value: Any) -> bytes:
    if target.is_setting:
        return setting_blob(value)
    return bytes(value)


def _encode(target: Target, blob: bytes) -> Any:
    if not target.is_setting:
        return blob
    return json.dumps({"enc": base64.b64encode(blob).decode("ascii"), "kid": key_id(blob)})


async def rotate(conn: AsyncConnection, cipher: Cipher, *, dry_run: bool = False) -> RotationReport:
    """Перешифровать значения на старых ключах. ``dry_run`` — только посчитать.

    Значение, которое не расшифровывается (неизвестный ключ, подмена), не трогается и
    попадает в ``errors`` с именем столбца и ключом строки — без содержимого.
    """
    report = RotationReport(current_kid=cipher.current_kid)
    for target in TARGETS:
        rep = report.targets.setdefault(target.name, TargetReport())
        rows = (await conn.execute(text(target.select_sql))).all()
        for row_id, value in rows:
            if target.is_setting and not is_encrypted_setting(value):
                continue
            rep.total += 1
            try:
                blob = _blob(target, value)
                if not cipher.needs_rotation(blob):
                    continue
                rep.on_old_keys += 1
                if dry_run:
                    cipher.decrypt(blob, target.context(row_id))  # проверить, что читается
                    continue
                new_blob = cipher.reencrypt(blob, target.context(row_id))
            except DecryptionError as exc:
                rep.errors.append(f"{target.name} [{row_id}]: {exc}")
                continue
            old_param = json.dumps(value) if target.is_setting else blob
            result = await conn.execute(
                text(target.update_sql),
                {"id": row_id, "old": old_param, "new": _encode(target, new_blob)},
            )
            if result.rowcount == 1:
                rep.reencrypted += 1
            else:
                rep.changed_concurrently += 1
                rep.on_old_keys -= 1
    return report
