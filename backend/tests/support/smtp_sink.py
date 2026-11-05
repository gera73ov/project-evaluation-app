"""Минимальная SMTP-ловушка для тестов NTF-002 (вместо Mailpit, который есть только на стенде).

Поддерживает EHLO/HELO, AUTH PLAIN, MAIL, RCPT, DATA, RSET, NOOP, QUIT. Принятые письма —
в :attr:`SmtpSink.messages` (``email.message.EmailMessage``), учётные данные AUTH — в
:attr:`SmtpSink.logins`. ``fail_codes`` — очередь кодов ответа на MAIL FROM (проверка повторов).
"""

from __future__ import annotations

import base64
import socketserver
import threading
from email import message_from_bytes, policy
from email.message import EmailMessage


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())

    def handle(self) -> None:
        sink = self.server.sink
        self._send("220 sink ESMTP")
        mail_from, rcpts = None, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            cmd = line.split(" ", 1)[0].upper()
            if cmd in ("EHLO", "HELO"):
                self._send("250-sink")
                self._send("250-AUTH PLAIN")
                self._send("250 8BITMIME")
            elif cmd == "AUTH":
                parts = line.split()
                payload = parts[2] if len(parts) > 2 else ""
                if not payload:
                    self._send("334 ")
                    payload = self.rfile.readline().decode().strip()
                _, user, password = base64.b64decode(payload).decode().split("\0")
                sink.logins.append((user, password))
                ok = sink.password is None or password == sink.password
                self._send("235 ok" if ok else "535 bad credentials")
            elif cmd == "MAIL":
                if sink.fail_codes:
                    code = sink.fail_codes.pop(0)
                    self._send(f"{code} try later")
                    continue
                mail_from, rcpts = line, []
                self._send("250 ok")
            elif cmd == "RCPT":
                rcpts.append(line.split(":", 1)[1].strip(" <>"))
                self._send("250 ok")
            elif cmd == "DATA":
                self._send("354 go")
                data = []
                while True:
                    chunk = self.rfile.readline()
                    if chunk in (b".\r\n", b".\n", b""):
                        break
                    data.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                msg = message_from_bytes(b"".join(data), policy=policy.default)
                sink.messages.append(msg)  # type: ignore[arg-type]
                sink.envelopes.append((mail_from, list(rcpts)))
                self._send("250 queued")
            elif cmd in ("RSET", "NOOP"):
                self._send("250 ok")
            elif cmd == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("502 not implemented")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    sink: SmtpSink


class SmtpSink:
    def __init__(self, password: str | None = None) -> None:
        self.password = password
        self.messages: list[EmailMessage] = []
        self.envelopes: list[tuple[str | None, list[str]]] = []
        self.logins: list[tuple[str, str]] = []
        self.fail_codes: list[int] = []
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.sink = self
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> SmtpSink:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
