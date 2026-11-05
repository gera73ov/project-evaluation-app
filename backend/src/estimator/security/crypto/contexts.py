"""Контексты (AAD) зашифрованных столбцов (SEC-003).

Контекст привязывает шифротекст к месту хранения: значение из одной строки или столбца,
скопированное в другую, не расшифруется. Все, кто пишет или читает эти столбцы (AUTH-006,
ADM, NTF-002, документы), берут контекст отсюда; ротация (:mod:`.rotation`) — тоже.
"""

from __future__ import annotations

from uuid import UUID

from estimator.security.crypto.aead import setting_context

__all__ = ["document_key", "setting_context", "totp_secret"]


def totp_secret(user_id: UUID | str) -> str:
    """``users.totp_secret_enc`` (SEC-CRYPT-03)."""
    return f"users.totp_secret_enc:{user_id}"


def document_key(document_id: UUID | str) -> str:
    """``customer_documents.key_enc`` — ключ данных файла под мастер-ключом (SEC-CRYPT-06)."""
    return f"customer_documents.key_enc:{document_id}"
