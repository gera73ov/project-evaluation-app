"""Источники нагрузки на журнал аудита для TC-AUD-01 (QA-010; SPEC SEC-AUD-03, RISK-05).

Пишут события тем же путём, что и приложение: :func:`estimator.security.audit.write_standalone`
через движок процесса (пул соединений, роль ``estimator_app``), каждое событие — в своей
транзакции, как отказ доступа или неудачный вход.

* ``app`` — ASGI-приложение для процессов Uvicorn (две «реплики api»): ``POST /load`` пишет
  ``n`` событий, ``parallel`` транзакций одновременно;
* ``celery`` — приложение Celery для настоящего worker: задача :data:`TASK` пишет ``n``
  событий в ``asyncio.run``, как задачи приложения (``estimator.security.tasks``).

Источник события виден в ``user_agent`` (``tc-aud-01/<source>``): тест проверяет, что записи
разных процессов действительно перемежаются.
"""

from __future__ import annotations

import asyncio
import os

from celery import Celery
from fastapi import FastAPI

EVENT = "auth.login.failed"
LOGIN = "tc-aud-01"
TASK = "tests.audit_load"
QUEUE = "tc-aud-01"
SOURCE = os.environ.get("AUDIT_LOAD_SOURCE", f"pid-{os.getpid()}")


async def write_events(n: int, parallel: int, source: str) -> int:
    from estimator.security import audit

    semaphore = asyncio.Semaphore(parallel)

    async def one(i: int) -> None:
        async with semaphore:
            await audit.write_standalone(
                EVENT, "failure", login=LOGIN, ip="10.0.0.1",
                user_agent=f"tc-aud-01/{source}", details={"reason": "invalid_credentials"},
            )  # fmt: skip

    await asyncio.gather(*(one(i) for i in range(n)))
    return n


app = FastAPI()


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/load")
async def load(n: int, parallel: int = 8) -> dict[str, int]:
    return {"written": await write_events(n, parallel, SOURCE)}


def _celery() -> Celery:
    broker = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/15")
    celery = Celery("tc_aud_01", broker=broker)
    celery.conf.update(
        task_default_queue=QUEUE,
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
        worker_prefetch_multiplier=1,
        worker_hijack_root_logger=False,
    )
    return celery


celery = _celery()


@celery.task(name=TASK)
def load_task(n: int, parallel: int = 4) -> int:
    from estimator.db.session import dispose_engine

    async def main() -> int:
        try:
            return await write_events(n, parallel, SOURCE)
        finally:
            await dispose_engine()  # цикл событий задачи закрывается — пул тоже

    return asyncio.run(main())
