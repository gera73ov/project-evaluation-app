"""QA-001 · несколько процессов API и клиенты WebSocket для сквозных тестов.

SPEC 13.2–13.3: за Nginx работают две реплики ``api``, правка из одной доходит до клиентов
другой через Redis pub/sub. Тесты совместной работы (TC-CONC-*, TC-AUD-01, G-13) поэтому
запускают два настоящих процесса Uvicorn и подключаются к ним как браузеры:

* :func:`api_processes` — фабрика: ``start(n=2, app=..., env={...})`` поднимает процессы на
  свободных портах 127.0.0.1 и ждёт ``/health/live``; после теста процессы останавливаются;
* :func:`two_api_processes` — готовая пара процессов приложения ``estimator.main:app_factory``;
* :func:`ws_connect` — фабрика клиентов WebSocket; все соединения закрываются после теста.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect

BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_APP = "estimator.main:app_factory"
START_TIMEOUT_SECONDS = 20.0


@dataclass
class ApiProcess:
    """Запущенный процесс Uvicorn."""

    port: int
    process: subprocess.Popen[bytes]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_base_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_api(
    app: str = DEFAULT_APP, *, factory: bool = True, env: Mapping[str, str] | None = None
) -> ApiProcess:
    """Запустить Uvicorn с приложением ``app`` и дождаться ``/health/live`` (или любого ответа)."""
    port = free_port()
    command = [sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port)]
    if factory:
        command.append("--factory")
    process = subprocess.Popen(  # noqa: S603 — фиксированная команда без пользовательского ввода
        command,
        cwd=BACKEND,
        env={**os.environ, "APP_ENV": "test", "LOG_LEVEL": "WARNING", **(env or {})},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    api = ApiProcess(port=port, process=process)
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
            raise RuntimeError(f"процесс {app} завершился при старте:\n{stderr[-2000:]}")
        try:
            httpx.get(f"{api.base_url}/health/live", timeout=0.5)
        except httpx.TransportError:
            time.sleep(0.1)
            continue
        return api
    api.stop()
    raise TimeoutError(f"процесс {app} не ответил за {START_TIMEOUT_SECONDS} с")


StartApi = Callable[..., list[ApiProcess]]


@pytest.fixture
def api_processes() -> Iterator[StartApi]:
    """Фабрика процессов API: ``start(n=2, app=..., factory=True, env=None)``."""
    started: list[ApiProcess] = []

    def start(
        n: int = 2,
        app: str = DEFAULT_APP,
        *,
        factory: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> list[ApiProcess]:
        batch = [start_api(app, factory=factory, env=env) for _ in range(n)]
        started.extend(batch)
        return batch

    yield start
    for api in started:
        api.stop()


@pytest.fixture
def two_api_processes(api_processes: StartApi) -> tuple[ApiProcess, ApiProcess]:
    """Два процесса приложения, как две реплики ``api`` за Nginx."""
    first, second = api_processes(2)
    return first, second


WsConnect = Callable[..., Awaitable[ClientConnection]]


@pytest.fixture
async def ws_connect() -> AsyncIterator[WsConnect]:
    """Фабрика клиентов WS: ``conn = await ws_connect(url, headers={"Cookie": ...})``."""
    opened: list[ClientConnection] = []

    async def make(url: str, headers: Mapping[str, str] | None = None) -> ClientConnection:
        conn = await connect(url, additional_headers=dict(headers or {}), open_timeout=5)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        await conn.close()
