"""Заглушка ``clamd`` для локального стенда e2e без контейнера ClamAV (FE-092).

Понимает только ``zINSTREAM``: читает блоки с длиной, в ответ ``stream: OK`` или, если в потоке
есть тестовая строка EICAR, ``stream: Eicar-Test-Signature FOUND``. На dev-стенде работает
настоящий ``clamav`` из compose; заглушка нужна только при запуске API без Docker:

    python3 e2e/tools/fake_clamd.py [порт, по умолчанию 3310]

и ``CLAMAV_HOST=127.0.0.1`` у API и worker. Только для локальных прогонов.
"""

from __future__ import annotations

import socketserver
import struct
import sys

EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


def _read(rfile, size: int) -> bytes:
    data = rfile.read(size)
    if len(data) != size:
        raise ConnectionError("поток оборван")
    return data


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        command = b""
        while not command.endswith(b"\x00"):
            command += _read(self.rfile, 1)
        if command != b"zINSTREAM\x00":
            self.wfile.write(b"UNKNOWN COMMAND\x00")
            return
        body = b""
        while True:
            (size,) = struct.unpack(">I", _read(self.rfile, 4))
            if size == 0:
                break
            body += _read(self.rfile, size)
        verdict = b"Eicar-Test-Signature FOUND" if EICAR in body else b"OK"
        self.wfile.write(b"stream: " + verdict + b"\x00")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3310
    with Server(("127.0.0.1", port), Handler) as server:
        server.serve_forever()
