"""SEC-012: передача аудита в SIEM (SEC-AUD-05, GAP-09, Q-39).

Тестовый приёмник syslog по TLS из ``deploy/syslog`` (тот же, что в compose): события доходят по
порядку, после простоя приёмника досылаются без потерь, сертификат SIEM проверяется по УЦ и
имени хоста, клиентский сертификат (mTLS) — по настройке.
"""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.security import audit
from estimator.security.siem import shipper
from tests.integration.auth.conftest import set_setting

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "deploy" / "syslog"))
sys.path.insert(0, str(ROOT / "deploy" / "certs"))

import gen_dev_certs  # noqa: E402
import receiver  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.spec("SEC-AUD-05")]


@pytest.fixture(scope="module")
def certs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("siem-certs")
    gen_dev_certs.issue(out)
    return out


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> str:
    """Свои ключи Redis у каждого теста: процессы xdist не делят курсор."""
    tag = uuid.uuid4().hex[:8]
    for name in ("CURSOR_KEY", "STDOUT_CURSOR_KEY", "STATE_KEY"):
        monkeypatch.setattr(shipper, name, f"test:{tag}:{getattr(shipper, name)}")
    return tag


class Receiver:
    def __init__(self, certs: Path, out: Path, *, require_client: bool = False) -> None:
        self.out = out
        receiver.Handler.output = out
        ctx = receiver.make_context(str(certs / "syslog.crt"), str(certs / "syslog.key"),
                                    str(certs / "ca.crt"), require_client)  # fmt: skip
        self.server = receiver.TLSServer(("127.0.0.1", 0), ctx)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def lines(self, n: int) -> list[str]:
        for _ in range(100):
            if self.out.exists() and len(got := self.out.read_text().splitlines()) >= n:
                return got
            time.sleep(0.05)
        return self.out.read_text().splitlines() if self.out.exists() else []


@pytest.fixture
def siem(certs: Path, tmp_path: Path) -> Iterator[Receiver]:
    server = Receiver(certs, tmp_path / "messages.log")
    yield server
    server.stop()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _configure(db: AsyncSession, certs: Path, port: int, **extra: Any) -> None:
    value = {
        "enabled": True,
        "host": "localhost",
        "port": port,
        "ca_cert_pem": (certs / "ca.crt").read_text(),
        "client_cert_pem": None,
        **extra,
    }
    await set_setting(db, shipper.SETTING, value)


async def _events(db: AsyncSession, n: int) -> list[str]:
    marks = [uuid.uuid4().hex[:10] for _ in range(n)]
    for mark in marks:
        await audit.write(db, "auth.login.failed", "failure", login=mark, ip="10.1.1.1",
                          details={"reason": "wrong_password"}, actor="anonymous")  # fmt: skip
    return marks


async def _start_at_end(db: AsyncSession, redis: Redis) -> None:
    end = int(await db.scalar(shipper._MAX_ID) or 0)
    await redis.set(shipper.CURSOR_KEY, end)
    await redis.set(shipper.STDOUT_CURSOR_KEY, end)


def _bodies(lines: Sequence[str]) -> list[dict[str, Any]]:
    return [json.loads(line.split(" - audit - ", 1)[1]) for line in lines]


async def test_events_reach_siem_in_order_and_stdout(
    db_session: AsyncSession, redis_client: Redis, certs: Path, siem: Receiver, keys: str
) -> None:
    await _configure(db_session, certs, siem.port)
    await _start_at_end(db_session, redis_client)
    marks = await _events(db_session, 3)
    out = io.StringIO()
    result = await shipper.ship(db_session, redis_client, out=out, host="api-1")
    assert (result.sent, result.printed, result.backlog, result.error) == (3, 3, 0, None)
    lines = siem.lines(3)
    assert [b["login"] for b in _bodies(lines)] == marks
    first = lines[0]
    assert first.startswith(f"<{13 * 8 + 4}>1 ")  # log audit, warning: неудачный вход
    assert " api-1 estimator - audit - " in first
    body = _bodies(lines)[0]
    assert body["type"] == "auth.login.failed"
    assert body["category"] == "auth"
    assert len(body["hash"]) == 64
    assert out.getvalue().splitlines() == lines
    state = await shipper.state(redis_client)
    assert state is not None
    assert (state["ok"], state["backlog"]) == (True, 0)


@pytest.mark.spec("Q-39")
async def test_queue_survives_siem_downtime(
    db_session: AsyncSession, redis_client: Redis, certs: Path, tmp_path: Path, keys: str
) -> None:
    port = _free_port()
    await _configure(db_session, certs, port)
    await _start_at_end(db_session, redis_client)
    marks = await _events(db_session, 4)
    down = await shipper.ship(db_session, redis_client, out=io.StringIO())
    assert down.sent == 0
    assert down.backlog == 4
    assert down.error
    state = await shipper.state(redis_client)
    assert state is not None
    assert state["ok"] is False

    later = await _events(db_session, 2)
    server = Receiver(certs, tmp_path / "late.log")
    try:
        await _configure(db_session, certs, server.port)
        up = await shipper.ship(db_session, redis_client, out=io.StringIO())
        assert (up.sent, up.backlog, up.error) == (6, 0, None)
        assert [b["login"] for b in _bodies(server.lines(6))] == marks + later
    finally:
        server.stop()


@pytest.mark.spec("GAP-09")
async def test_certificate_is_verified(
    db_session: AsyncSession, redis_client: Redis, certs: Path, siem: Receiver, keys: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:  # fmt: skip
    other = tmp_path_factory.mktemp("other-ca")
    gen_dev_certs.issue(other)
    await _start_at_end(db_session, redis_client)
    await _events(db_session, 1)
    await _configure(db_session, certs, siem.port, ca_cert_pem=(other / "ca.crt").read_text())
    wrong_ca = await shipper.ship(db_session, redis_client, out=io.StringIO())
    assert wrong_ca.sent == 0
    assert "CERTIFICATE_VERIFY_FAILED" in (wrong_ca.error or "")

    await _configure(db_session, certs, siem.port, host="127.0.0.2")
    wrong_host = await shipper.ship(db_session, redis_client, out=io.StringIO())
    assert wrong_host.sent == 0

    await _configure(db_session, certs, siem.port, ca_cert_pem=None)
    no_ca = await shipper.ship(db_session, redis_client, out=io.StringIO())
    assert no_ca.error == "не загружен сертификат УЦ SIEM"
    assert no_ca.backlog == 1
    assert siem.lines(1) == []


@pytest.mark.spec("GAP-09")
async def test_mutual_tls(
    db_session: AsyncSession, redis_client: Redis, certs: Path, tmp_path: Path, keys: str
) -> None:
    server = Receiver(certs, tmp_path / "mtls.log", require_client=True)
    try:
        await _start_at_end(db_session, redis_client)
        await _events(db_session, 1)
        await _configure(db_session, certs, server.port)
        marks = await _events(db_session, 1)
        without = await shipper.ship(db_session, redis_client, out=io.StringIO())
        assert without.sent == 0  # отказ сервера после передачи кадра (TLS 1.3) — не доставлено
        assert without.backlog == 2
        await _configure(db_session, certs, server.port,
                         client_cert_pem=(certs / "siem-client.crt").read_text())  # fmt: skip
        await set_setting(db_session, shipper.KEY_SETTING, (certs / "siem-client.key").read_text())
        with_cert = await shipper.ship(db_session, redis_client, out=io.StringIO())
        assert with_cert.sent == 2
        assert [b["login"] for b in _bodies(server.lines(2))][-1] == marks[0]
    finally:
        server.stop()


async def test_overflow_drops_oldest(
    db_session: AsyncSession, redis_client: Redis, certs: Path, keys: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setattr(shipper, "MAX_QUEUE", 2)
    sent: list[bytes] = []
    await _configure(db_session, certs, 1)
    await _start_at_end(db_session, redis_client)
    marks = await _events(db_session, 5)
    result = await shipper.ship(db_session, redis_client, out=io.StringIO(),
                                sender=lambda _c, frames: sent.extend(frames))  # fmt: skip
    assert (result.sent, result.dropped) == (2, 3)
    assert [b["login"] for b in _bodies([f.decode().split(" ", 1)[1] for f in sent])] == marks[3:]
    state = await shipper.state(redis_client)
    assert state is not None
    assert state["overflow_at"]
    assert state["dropped"] == 3


async def test_disabled_siem_does_not_queue(
    db_session: AsyncSession, redis_client: Redis, keys: str
) -> None:
    off = {"enabled": False, "host": None, "port": 6514, "ca_cert_pem": None,
           "client_cert_pem": None}  # fmt: skip
    await set_setting(db_session, shipper.SETTING, off)
    await redis_client.delete(shipper.CURSOR_KEY, shipper.STDOUT_CURSOR_KEY)
    out = io.StringIO()
    first = await shipper.ship(db_session, redis_client, out=out)
    assert first.printed == 0  # копия в stdout начинается с конца журнала
    marks = await _events(db_session, 2)
    result = await shipper.ship(db_session, redis_client, out=out)
    assert (result.sent, result.printed, result.backlog) == (0, 2, 0)
    assert [b["login"] for b in _bodies(out.getvalue().splitlines())] == marks
    end = int(await db_session.scalar(shipper._MAX_ID) or 0)
    assert int(await redis_client.get(shipper.CURSOR_KEY) or 0) == end


def test_periodic_task_runs_one_pass(
    monkeypatch: pytest.MonkeyPatch, test_database_url: str, keys: str
) -> None:
    import os

    from estimator.config import get_settings
    from estimator.jobs.schedule import build_beat_schedule
    from estimator.security.siem import tasks

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    monkeypatch.setattr(tasks, "LOCK_KEY", f"test:{keys}:lock")
    get_settings.cache_clear()
    assert build_beat_schedule()["siem_ship"]["task"] == tasks.SHIP_TASK
    assert tasks.ship.apply().get() == 0  # SIEM в тестовой базе выключен — отправлять некуда


async def test_state_is_readable_synchronously(redis_client: Redis, keys: str) -> None:
    import os

    await redis_client.set(shipper.STATE_KEY, json.dumps({"enabled": True, "backlog": 3}))
    url = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    assert shipper.read_state_sync(url) == {"enabled": True, "backlog": 3}
    await redis_client.delete(shipper.STATE_KEY)
    assert shipper.read_state_sync(url) is None
