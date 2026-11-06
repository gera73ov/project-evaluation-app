"""TC-AUD-01 (QA-010): параллельная запись аудита из нескольких процессов не ломает цепочку.

SPEC SEC-AUD-03, TC-AUD-01, RISK-05. Две «реплики api» (процессы Uvicorn) и настоящий worker
Celery одновременно пишут не меньше 10 000 событий; затем консольная команда
``estimator audit verify`` проверяет хэш-цепочку всего журнала.

Тест долгий (десятки секунд), поэтому помечен ``nightly`` и в проверках PR не запускается;
его гоняет плановое задание (``.github/workflows/nightly.yml``). Число событий для локального
прогона можно уменьшить переменной ``TC_AUD_01_EVENTS``.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from tests.plugins.processes import StartApi
from tests.support import audit_load

pytestmark = [
    pytest.mark.integration,
    pytest.mark.nightly,
    pytest.mark.tc("TC-AUD-01"),
    pytest.mark.spec("SEC-AUD-03"),
]

BACKEND = Path(__file__).resolve().parents[2]
TOTAL = int(os.environ.get("TC_AUD_01_EVENTS", "10000"))
API_SHARE = 0.4  # по 40 % на каждый процесс api, 20 % — worker
BATCH = 100
WORKER_TIMEOUT_SECONDS = 600.0


def _env(database_url: str, broker: str, source: str) -> dict[str, str]:
    return {
        **os.environ,
        "APP_ENV": "test",
        "LOG_LEVEL": "WARNING",
        "DATABASE_URL": database_url,
        "CELERY_BROKER_URL": broker,
        "AUDIT_LOAD_SOURCE": source,
    }


@pytest.fixture
def broker() -> str:
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL не задан: брокер Celery недоступен")
    return url


@pytest.fixture
def celery_worker(test_database_url: str, broker: str) -> Iterator[subprocess.Popen[bytes]]:
    """Настоящий worker Celery (prefork, 2 процесса) на отдельной очереди теста."""
    audit_load.celery.conf.broker_url = broker
    audit_load.celery.control.purge()
    command = [
        sys.executable, "-m", "celery", "-A", "tests.support.audit_load:celery", "worker",
        "-Q", audit_load.QUEUE, "--concurrency", "2", "--loglevel", "WARNING", "--without-gossip",
        "--without-mingle", "--without-heartbeat",
    ]  # fmt: skip
    process = subprocess.Popen(  # noqa: S603 — фиксированная команда без пользовательского ввода
        command,
        cwd=BACKEND,
        env=_env(test_database_url, broker, "worker"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    yield process
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


async def _count(database_url: str) -> int:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            value = await conn.scalar(
                text("SELECT count(*) FROM audit.audit_log WHERE login = :l"),
                {"l": audit_load.LOGIN},
            )
            return int(value or 0)
    finally:
        await engine.dispose()


async def _sources_in_order(database_url: str) -> list[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT user_agent FROM audit.audit_log WHERE login = :l ORDER BY id"),
                {"l": audit_load.LOGIN},
            )
            return [r[0] for r in rows.all()]
    finally:
        await engine.dispose()


def _batches(total: int) -> list[int]:
    full, rest = divmod(total, BATCH)
    return [BATCH] * full + ([rest] if rest else [])


async def _drive_api(base_url: str, total: int) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:

        async def one(n: int) -> None:
            response = await client.post("/load", params={"n": n, "parallel": 8})
            assert response.status_code == 200, response.text
            assert response.json() == {"written": n}

        # Несколько запросов одновременно: пул соединений процесса работает в полную силу
        semaphore = asyncio.Semaphore(4)

        async def limited(n: int) -> None:
            async with semaphore:
                await one(n)

        await asyncio.gather(*(limited(n) for n in _batches(total)))


async def _wait_for(database_url: str, expected: int, worker: subprocess.Popen[bytes]) -> int:
    deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
    count = await _count(database_url)
    while count < expected and time.monotonic() < deadline:
        if worker.poll() is not None:
            stderr = worker.stderr.read().decode(errors="replace") if worker.stderr else ""
            pytest.fail(f"worker Celery завершился:\n{stderr[-2000:]}")
        await asyncio.sleep(0.5)
        count = await _count(database_url)
    return count


async def test_parallel_writers_keep_chain(
    api_processes: StartApi,
    celery_worker: subprocess.Popen[bytes],
    test_database_url: str,
    broker: str,
) -> None:
    before = await _count(test_database_url)
    per_api = int(TOTAL * API_SHARE)
    worker_total = TOTAL - 2 * per_api
    apis = [
        api_processes(1, "tests.support.audit_load:app", factory=False,
                      env=_env(test_database_url, broker, f"api-{i}"))[0]
        for i in (1, 2)
    ]  # fmt: skip

    # Сначала очередь worker, затем обе реплики api — все три источника пишут одновременно
    for n in _batches(worker_total):
        audit_load.load_task.apply_async(args=[n], queue=audit_load.QUEUE)
    await asyncio.gather(*(_drive_api(api.base_url, per_api) for api in apis))

    count = await _wait_for(test_database_url, before + TOTAL, celery_worker)
    assert count == before + TOTAL, f"записано {count - before} из {TOTAL}"

    # Источники перемежаются: запись действительно шла параллельно, а не по очереди
    sources = await _sources_in_order(test_database_url)
    assert {s.removeprefix("tc-aud-01/") for s in sources} == {"api-1", "api-2", "worker"}
    switches = sum(1 for a, b in itertools.pairwise(sources) if a != b)
    assert switches >= 50, f"смен источника всего {switches}: записи шли последовательно"

    verify = await asyncio.to_thread(
        subprocess.run,  # фиксированная команда без пользовательского ввода (S603)
        [str(Path(sys.executable).with_name("estimator")), "audit", "verify"],
        cwd=BACKEND,
        env=_env(test_database_url, broker, "cli"),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert "Цепочка цела" in verify.stdout
