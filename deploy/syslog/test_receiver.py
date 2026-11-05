"""INF-004: тестовый syslog-приёмник TLS (SEC-AUD-05, GAP-09)."""

from __future__ import annotations

import contextlib
import socket
import ssl
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "certs"))

import gen_dev_certs
import receiver


@pytest.mark.parametrize(
    ("data", "messages", "rest"),
    [
        (b"11 <13>1 hello", [b"<13>1 hello"], b""),
        (b"5 abcde3 xyz", [b"abcde", b"xyz"], b""),
        (b"10 short", [], b"10 short"),
        (b"<13>1 a\n<13>1 b\r\nc", [b"<13>1 a", b"<13>1 b"], b"c"),
        (b"12", [], b"12"),
    ],
)
def test_split_frames(data: bytes, messages: list[bytes], rest: bytes) -> None:
    buf = bytearray(data)
    assert receiver.split_frames(buf) == messages
    assert bytes(buf) == rest


@pytest.mark.parametrize("data", [b"99999999999", b"999999 x", b"x" * (receiver.MAX_MESSAGE + 1)])
def test_split_frames_rejects_oversize(data: bytes) -> None:
    with pytest.raises(ValueError, match="длин"):
        receiver.split_frames(bytearray(data))


@pytest.fixture(scope="module")
def certs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("certs")
    assert "syslog" in gen_dev_certs.issue(out)
    assert gen_dev_certs.issue(out) == []  # повторный запуск ничего не перезаписывает
    return out


def _serve(certs: Path, tmp_path: Path, require_client: bool):
    receiver.Handler.output = tmp_path / "messages.log"
    ctx = receiver.make_context(
        str(certs / "syslog.crt"), str(certs / "syslog.key"), str(certs / "ca.crt"), require_client
    )
    server = receiver.TLSServer(("127.0.0.1", 0), ctx)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _client_ctx(certs: Path, with_cert: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(certs / "ca.crt"))
    if with_cert:
        ctx.load_cert_chain(str(certs / "siem-client.crt"), str(certs / "siem-client.key"))
    return ctx


def _send(server, ctx: ssl.SSLContext, payload: bytes, host: str = "localhost") -> None:
    with (
        socket.create_connection(server.server_address, timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname=host) as tls,
    ):
        tls.sendall(payload)


def _wait_lines(path: Path, n: int) -> list[str]:
    import time

    for _ in range(100):
        if path.exists() and len(lines := path.read_text().splitlines()) >= n:
            return lines
        time.sleep(0.05)
    return path.read_text().splitlines() if path.exists() else []


def test_receives_rfc5425_over_tls(certs: Path, tmp_path: Path) -> None:
    server = _serve(certs, tmp_path, require_client=False)
    try:
        msg = b'<110>1 2026-11-05T09:00:00Z host estimator - audit - {"event":"login"}'
        _send(server, _client_ctx(certs, with_cert=False), f"{len(msg)} ".encode() + msg)
        assert _wait_lines(tmp_path / "messages.log", 1) == [msg.decode()]
    finally:
        server.shutdown()
        server.server_close()


def test_hostname_is_verified(certs: Path, tmp_path: Path) -> None:
    server = _serve(certs, tmp_path, require_client=False)
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            _send(server, _client_ctx(certs, with_cert=False), b"x\n", host="wrong.example")
    finally:
        server.shutdown()
        server.server_close()


def test_mtls_required(certs: Path, tmp_path: Path) -> None:
    server = _serve(certs, tmp_path, require_client=True)
    try:
        _send(server, _client_ctx(certs, with_cert=True), b"<13>1 with-cert\n")
        assert _wait_lines(tmp_path / "messages.log", 1) == ["<13>1 with-cert"]
        # без клиентского сертификата сервер рвёт соединение
        with contextlib.suppress(ssl.SSLError, ConnectionError):
            _send(server, _client_ctx(certs, with_cert=False), b"<13>1 no-cert\n")
        assert "<13>1 no-cert" not in _wait_lines(tmp_path / "messages.log", 2)
    finally:
        server.shutdown()
        server.server_close()
