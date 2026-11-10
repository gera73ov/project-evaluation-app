"""Проверка антивирусом ClamAV (EXP-011; SPEC SEC-WEB-10, 13.1 «Антивирус»).

Клиент ``clamd`` по TCP, команда ``zINSTREAM``: блоки с длиной (4 байта, big-endian), в конце
блок нулевой длины; ответ ``stream: OK``, ``stream: <сигнатура> FOUND`` или ``… ERROR``.
Открытый текст подаётся в сокет прямо из расшифровки и на диск не пишется.

Сканер подменяемый (:data:`scanner`): тесты ставят свой, без контейнера ``clamav``.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from estimator.config import get_settings
from estimator.db.enums import ScanStatus

CHUNK = 64 * 1024


@dataclass(frozen=True)
class Verdict:
    status: ScanStatus  # CLEAN, INFECTED или ERROR
    signature: str | None = None


class ScannerUnavailable(Exception):
    """``clamd`` недоступен: проверку стоит повторить позже."""


class Sink(Protocol):
    def write(self, data: bytes, /) -> int: ...


#: Подаёт открытый текст документа в приёмник (расшифровка файла хранения).
Feed = Callable[[Sink], object]


class Scanner(Protocol):
    def __call__(self, feed: Feed) -> Verdict: ...


class _Stream:
    """Приёмник, который режет поток на блоки INSTREAM."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def write(self, data: bytes, /) -> int:
        view = memoryview(data)
        for start in range(0, len(view), CHUNK):
            part = view[start : start + CHUNK]
            self.sock.sendall(struct.pack(">I", len(part)) + bytes(part))
        return len(data)


def parse_reply(reply: bytes) -> Verdict:
    text = reply.rstrip(b"\x00\n").decode("utf-8", "replace").strip()
    body = text.split(":", 1)[1].strip() if ":" in text else text
    if body == "OK":
        return Verdict(ScanStatus.CLEAN)
    if body.endswith(" FOUND"):
        return Verdict(ScanStatus.INFECTED, body.removesuffix(" FOUND").strip()[:200] or None)
    return Verdict(ScanStatus.ERROR)


def clamd(feed: Feed) -> Verdict:  # pragma: no cover — нужен контейнер clamav
    """Проверить поток в ``clamd`` (``CLAMAV_HOST``:``CLAMAV_PORT``)."""
    settings = get_settings()
    try:
        sock = socket.create_connection(
            (settings.clamav_host, settings.clamav_port), timeout=settings.clamav_timeout_seconds
        )
    except OSError as exc:
        raise ScannerUnavailable(str(exc)) from exc
    with sock:
        try:
            sock.sendall(b"zINSTREAM\x00")
            feed(_Stream(sock))
            sock.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\x00"):
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
        except OSError as exc:
            # clamd закрывает соединение, когда поток длиннее StreamMaxLength
            if isinstance(exc, ConnectionError):
                return Verdict(ScanStatus.ERROR)
            raise ScannerUnavailable(str(exc)) from exc
    return parse_reply(reply)


#: Текущий сканер; тесты подменяют его.
scanner: Scanner = clamd
