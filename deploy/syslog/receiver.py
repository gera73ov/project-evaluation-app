"""Тестовый syslog-приёмник по TCP+TLS — эмулятор SIEM для dev и test (INF-004).

SEC-AUD-05: приложение шлёт события аудита в SIEM по syslog RFC 5424 поверх TCP+TLS
(RFC 5425); сертификат сервера проверяется, клиентский сертификат (mTLS) — опционально
(GAP-09). Приёмник принимает оба способа разбиения потока: octet-counting
(``<длина> <сообщение>``, RFC 5425/6587) и по переводу строки. Каждое сообщение пишется
отдельной строкой в stdout и в файл ``SYSLOG_OUTPUT`` — по нему интеграционные тесты SEC-012
проверяют доставку и досылку после простоя.

Только стандартная библиотека Python: образу не нужны пакеты ОС.

Переменные окружения:
  SYSLOG_BIND — адрес, SYSLOG_PORT (6514), SYSLOG_CERT, SYSLOG_KEY — сертификат и ключ сервера;
  SYSLOG_CLIENT_CA — УЦ для проверки клиентов; SYSLOG_REQUIRE_CLIENT_CERT=1 — требовать mTLS;
  SYSLOG_OUTPUT (/var/log/siem/messages.log).
"""

from __future__ import annotations

import os
import socketserver
import ssl
import sys
import threading
from pathlib import Path

MAX_MESSAGE = 64 * 1024
_write_lock = threading.Lock()


def split_frames(buffer: bytearray) -> list[bytes]:
    """Вырезать из буфера все целые сообщения; неполный хвост остаётся в буфере."""
    messages: list[bytes] = []
    while buffer:
        if buffer[:1].isdigit():
            space = buffer.find(b" ")
            if space == -1:
                if len(buffer) > 10:
                    raise ValueError("слишком длинный префикс длины")
                break
            length = int(buffer[:space])
            if length > MAX_MESSAGE:
                raise ValueError(f"сообщение длиннее {MAX_MESSAGE} байт")
            end = space + 1 + length
            if len(buffer) < end:
                break
            messages.append(bytes(buffer[space + 1 : end]))
            del buffer[:end]
        else:
            newline = buffer.find(b"\n")
            if newline == -1:
                if len(buffer) > MAX_MESSAGE:
                    raise ValueError(f"сообщение длиннее {MAX_MESSAGE} байт")
                break
            messages.append(bytes(buffer[:newline]).rstrip(b"\r"))
            del buffer[: newline + 1]
    return [m for m in messages if m]


class Handler(socketserver.BaseRequestHandler):
    output: Path

    def handle(self) -> None:
        buffer = bytearray()
        peer = self.client_address[0]
        try:
            while chunk := self.request.recv(65536):
                buffer += chunk
                for message in split_frames(buffer):
                    self._emit(message.decode("utf-8", errors="replace"))
        except (ssl.SSLError, ConnectionError, ValueError) as exc:
            print(f"syslog-receiver: соединение {peer} закрыто: {exc}", file=sys.stderr)

    def _emit(self, line: str) -> None:
        with _write_lock:
            print(line, flush=True)
            with self.output.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


class TLSServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: ssl.SSLContext) -> None:
        self.context = context
        super().__init__(address, Handler)

    def get_request(self):
        sock, addr = super().get_request()
        return self.context.wrap_socket(sock, server_side=True), addr


def make_context(
    cert: str, key: str, client_ca: str | None, require_client: bool
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    if client_ca:
        context.load_verify_locations(client_ca)
        context.verify_mode = ssl.CERT_REQUIRED if require_client else ssl.CERT_OPTIONAL
    return context


def main() -> None:
    port = int(os.environ.get("SYSLOG_PORT", "6514"))
    output = Path(os.environ.get("SYSLOG_OUTPUT", "/var/log/siem/messages.log"))
    output.parent.mkdir(parents=True, exist_ok=True)
    Handler.output = output
    context = make_context(
        os.environ["SYSLOG_CERT"],
        os.environ["SYSLOG_KEY"],
        os.environ.get("SYSLOG_CLIENT_CA") or None,
        os.environ.get("SYSLOG_REQUIRE_CLIENT_CERT", "0") == "1",
    )
    # адрес задаёт compose (SYSLOG_BIND): приёмник слушает только внутри сети стенда
    with TLSServer((os.environ["SYSLOG_BIND"], port), context) as server:
        print(f"syslog-receiver: слушаю TLS {port}, вывод в {output}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
