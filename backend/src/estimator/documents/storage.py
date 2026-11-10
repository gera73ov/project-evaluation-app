"""Файлы документов на томе ``documents``: путь по ``storage_key``, запись и чтение потока
(SEC-CRYPT-06: AES-256-GCM, свой ключ данных на файл, ключ — под мастер-ключом в БД)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import BinaryIO

from estimator.config import get_settings
from estimator.security.crypto import contexts, envelope, get_cipher


def storage_dir() -> Path:
    return Path(get_settings().documents_dir)


def path_of(storage_key: uuid.UUID) -> Path:
    """Имя хранения — UUID, имя файла пользователя на диск не попадает (SEC-WEB-10)."""
    return storage_dir() / str(storage_key)


def write_encrypted(src: BinaryIO, document_id: uuid.UUID, storage_key: uuid.UUID) -> bytes:
    """Зашифровать ``src`` новым ключом данных в файл хранения; вернуть ``key_enc``."""
    data_key = envelope.new_data_key()
    context = contexts.document_key(document_id)
    key_enc = envelope.wrap_data_key(get_cipher(), data_key, context)
    target = path_of(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    src.seek(0)
    with partial.open("wb") as dst:
        envelope.encrypt_stream(src, dst, data_key, str(document_id))
        dst.flush()
        os.fsync(dst.fileno())
    partial.replace(target)
    return key_enc


def read_decrypted(
    dst: BinaryIO, document_id: uuid.UUID, storage_key: uuid.UUID, key_enc: bytes
) -> int:
    """Расшифровать файл хранения в ``dst``; число байт открытого текста."""
    data_key = envelope.unwrap_data_key(get_cipher(), key_enc, contexts.document_key(document_id))
    with path_of(storage_key).open("rb") as src:
        return envelope.decrypt_stream(src, dst, data_key, str(document_id))


def remove(storage_key: uuid.UUID) -> None:
    path_of(storage_key).unlink(missing_ok=True)
