"""Общие фикстуры тестов бэкенда."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis

from estimator.config import get_settings
from estimator.security.alerts import notify as alerts_notify
from estimator.services.projects import totals

#: Адрес тестового Redis, например ``redis://127.0.0.1:6379/15``. Без него тесты с фикстурой
#: :func:`redis_client` пропускаются. Тесты не чистят базу: ключи у каждого теста свои
#: (случайные логины, IP, id), поэтому параллельные процессы xdist друг другу не мешают.
REDIS_ENV_VAR = "TEST_REDIS_URL"


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch):
    """Каждый тест читает окружение заново и не видит переменных разработчика."""
    for name in ("APP_ENV", "LOG_LEVEL", "APP_TIMEZONE", "TRUSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def totals_queue(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Постановка пересчёта кэша итогов (CORE-026) без брокера: id проектов по порядку."""
    calls: list[uuid.UUID] = []

    async def record(project_id: uuid.UUID) -> None:
        calls.append(project_id)

    monkeypatch.setattr(totals, "enqueue", record)
    return calls


@pytest.fixture(autouse=True)
def export_queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Any]:
    """Постановка выгрузок (EXP-003) без брокера: задания по порядку; файлы — во временном
    каталоге теста. Тест строит файл сам: ``await engine.run(db, job)``."""
    from estimator.exports import engine

    jobs: list[Any] = []

    async def record(job: Any) -> None:
        jobs.append(job)

    monkeypatch.setattr(engine, "dispatch", record)
    monkeypatch.setenv("EXPORTS_DIR", str(tmp_path / "exports"))
    return jobs


#: Тестовая строка EICAR: антивирусы считают её вирусом (SEC-WEB-10, TC-SEC-10).
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


@pytest.fixture(autouse=True)
def document_scans(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[uuid.UUID]:
    """Проверка документов (EXP-011) без брокера и ``clamd``: id документов по порядку; файлы —
    во временном каталоге теста; сканер находит EICAR. Тест проверяет сам:
    ``await tasks.check(db, document_id)``."""
    import io

    from estimator.db.enums import ScanStatus
    from estimator.documents import scan, tasks

    queued: list[uuid.UUID] = []

    async def record(document_id: uuid.UUID) -> None:
        queued.append(document_id)

    def fake_clamd(feed: Any) -> scan.Verdict:
        sink = io.BytesIO()
        feed(sink)
        if EICAR in sink.getvalue():
            return scan.Verdict(ScanStatus.INFECTED, "Eicar-Test-Signature")
        return scan.Verdict(ScanStatus.CLEAN)

    monkeypatch.setattr(tasks, "dispatch", record)
    monkeypatch.setattr(scan, "scanner", fake_clamd)
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "documents"))
    return queued


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Клиент тестового Redis (``TEST_REDIS_URL``)."""
    url = os.environ.get(REDIS_ENV_VAR)
    if not url:
        pytest.skip(f"{REDIS_ENV_VAR} не задан")
    client = Redis.from_url(url)
    yield client
    await client.aclose()


#: Долгие тесты (нагрузка, TC-AUD-01) идут только в плановом задании CI: ``RUN_NIGHTLY=1``.
NIGHTLY_ENV_VAR = "RUN_NIGHTLY"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(NIGHTLY_ENV_VAR) == "1":
        return
    skip = pytest.mark.skip(reason=f"долгий тест: запускается при {NIGHTLY_ENV_VAR}=1 (nightly)")
    for item in items:
        if item.get_closest_marker("nightly"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def alerts_queue(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Постановка рассылки оповещений ИБ (SEC-011) без брокера: аргументы вызовов по порядку."""
    calls: list[tuple] = []
    monkeypatch.setattr(alerts_notify, "enqueue", lambda *args: calls.append(args))
    return calls
