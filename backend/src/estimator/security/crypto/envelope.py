"""Envelope-шифрование документов заказчика (SEC-003; SEC-CRYPT-06).

На каждый файл — свой случайный ключ данных (AES-256). Ключ данных шифруется мастер-ключом
(:meth:`Cipher.encrypt` с контекстом :func:`contexts.document_key`) и хранится в
``customer_documents.key_enc``; сам файл на томе ``documents`` шифруется ключом данных.
При ротации мастер-ключа перешифровываются только ключи данных, файлы не трогаются.

Формат файла — потоковый AES-GCM по блокам (конструкция STREAM)::

    b"ESTD" | версия (1 байт) | префикс nonce (7 байт) | блок 0 | блок 1 | … | последний блок

Блок — до 64 КиБ открытого текста плюс тег 16 байт. Nonce блока = префикс ‖ номер блока
(4 байта) ‖ признак последнего блока (1 байт), AAD — контекст файла (id документа). Поэтому
перестановка, удаление и обрезка блоков обнаруживаются так же, как подмена байтов.
"""

from __future__ import annotations

import os
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from estimator.security.crypto.aead import Cipher, DecryptionError
from estimator.security.crypto.keys import KEY_BYTES

MAGIC = b"ESTD"
FILE_VERSION = 1
PREFIX_BYTES = 7
CHUNK = 64 * 1024
TAG = 16
HEADER_BYTES = len(MAGIC) + 1 + PREFIX_BYTES
MAX_CHUNKS = 2**32 - 1


def new_data_key() -> bytes:
    return os.urandom(KEY_BYTES)


def wrap_data_key(cipher: Cipher, data_key: bytes, context: str) -> bytes:
    """Зашифровать ключ данных мастер-ключом (значение для ``key_enc``)."""
    if len(data_key) != KEY_BYTES:
        raise ValueError("ключ данных — 32 байта")
    return cipher.encrypt(data_key, context)


def unwrap_data_key(cipher: Cipher, key_enc: bytes, context: str) -> bytes:
    data_key = cipher.decrypt(key_enc, context)
    if len(data_key) != KEY_BYTES:
        raise DecryptionError("ключ данных повреждён")
    return data_key


def _nonce(prefix: bytes, index: int, last: bool) -> bytes:
    if index > MAX_CHUNKS:
        raise ValueError("файл слишком большой для одного ключа данных")
    return prefix + index.to_bytes(4, "big") + (b"\x01" if last else b"\x00")


def _read_full(src: BinaryIO, size: int) -> bytes:
    parts: list[bytes] = []
    left = size
    while left:
        part = src.read(left)
        if not part:
            break
        parts.append(part)
        left -= len(part)
    return b"".join(parts)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, data_key: bytes, context: str) -> int:
    """Зашифровать поток ``src`` в ``dst``. Возвращает размер открытого текста в байтах."""
    aead = AESGCM(data_key)
    aad = context.encode("utf-8")
    prefix = os.urandom(PREFIX_BYTES)
    dst.write(MAGIC + bytes((FILE_VERSION,)) + prefix)
    total = 0
    index = 0
    chunk = _read_full(src, CHUNK)
    while True:
        following = _read_full(src, CHUNK) if len(chunk) == CHUNK else b""
        last = not following
        dst.write(aead.encrypt(_nonce(prefix, index, last), chunk, aad))
        total += len(chunk)
        if last:
            return total
        chunk = following
        index += 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO, data_key: bytes, context: str) -> int:
    """Расшифровать поток. Подмена, перестановка или обрезка — :class:`DecryptionError`.

    Открытый текст блока пишется в ``dst`` только после проверки его тега; при ошибке в
    середине файла начало уже записано, поэтому вызывающий отдаёт файл пользователю, только
    если функция завершилась без исключения (например, расшифровывает во временный файл).
    """
    header = _read_full(src, HEADER_BYTES)
    if len(header) != HEADER_BYTES or header[:4] != MAGIC or header[4] != FILE_VERSION:
        raise DecryptionError("файл не зашифрован приложением или повреждён")
    prefix = header[5:]
    aead = AESGCM(data_key)
    aad = context.encode("utf-8")
    total = 0
    index = 0
    block = _read_full(src, CHUNK + TAG)
    while True:
        following = _read_full(src, CHUNK + TAG) if len(block) == CHUNK + TAG else b""
        last = not following
        try:
            plain = aead.decrypt(_nonce(prefix, index, last), block, aad)
        except InvalidTag as exc:
            raise DecryptionError("файл подменён, обрезан или зашифрован другим ключом") from exc
        dst.write(plain)
        total += len(plain)
        if last:
            return total
        block = following
        index += 1
