"""INF-013 · метрики эксплуатации для правил оповещений SPEC 18.4.

Метрики запросов, входов, очередей и WebSocket считаются по ходу работы
(:mod:`estimator.metrics`, :mod:`estimator.realtime.metrics`, очередь SIEM —
:class:`~estimator.security.siem.shipper.QueueCollector`).
Состояние фоновых проверок (они идут в worker и beat, а Prometheus опрашивает только api) и
внешних служб API пересчитывает сам: фоновая задача каждого экземпляра раз в
:data:`INTERVAL_SECONDS` обновляет датчики ниже. Правила — ``deploy/monitoring/alerts.yml``.

* ``estimator_component_up{component}`` — индикаторы «Состояния системы» (FR-SA-07), 1/0;
* ``estimator_backup_last_success_timestamp_seconds`` — файл-метка последней копии (INF-012);
* ``estimator_wal_last_archived_timestamp_seconds``, ``estimator_wal_archive_failing`` — архивация
  WAL по ``pg_stat_archiver`` (последняя попытка неудачна — 1);
* ``estimator_ad_sync_last_success_timestamp_seconds{kind}`` — последняя выполненная проверка
  пользователей в AD (``sessions_15min``, ``daily``; AUTH-016);
* ``estimator_audit_chain_ok`` — последняя проверка цепочки аудита пройдена (SEC-AUD-03);
* ``estimator_cert_not_after_timestamp_seconds{cert}`` — окончание сертификата: ``app`` (TLS
  приложения, ``APP_TLS_CERT_PATH``) и ``ad_ca`` (УЦ контроллеров AD из настроек);
* ``estimator_clamav_up``, ``estimator_clamav_db_timestamp_seconds`` — clamd отвечает на ``VERSION``
  и дата его баз сигнатур.

Нет данных (метки нет, AD не используется, проверка ещё не шла) — датчик не выставляется: правила
различают «нет значения» (``absent``) и «старое значение».
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import email.utils
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimator.config import Settings
from estimator.logging import get_logger
from estimator.metrics import gauge

log = get_logger(__name__)

INTERVAL_SECONDS = 60.0

COMPONENT_UP = gauge(
    "estimator_component_up", "Индикатор «Состояния системы» зелёный (1/0)", ("component",)
)
BACKUP_LAST = gauge(
    "estimator_backup_last_success_timestamp_seconds", "Время последней успешной резервной копии"
)
WAL_LAST = gauge(
    "estimator_wal_last_archived_timestamp_seconds", "Время последнего заархивированного WAL"
)
WAL_FAILING = gauge(
    "estimator_wal_archive_failing", "Последняя попытка архивации WAL не удалась (1/0)"
)
AD_SYNC_LAST = gauge(
    "estimator_ad_sync_last_success_timestamp_seconds",
    "Время последней выполненной проверки пользователей в AD",
    ("kind",),
)
AUDIT_CHAIN_OK = gauge("estimator_audit_chain_ok", "Последняя проверка цепочки аудита пройдена")
CERT_NOT_AFTER = gauge(
    "estimator_cert_not_after_timestamp_seconds", "Окончание срока сертификата", ("cert",)
)
CLAMAV_UP = gauge("estimator_clamav_up", "clamd отвечает (1/0)")
CLAMAV_DB = gauge("estimator_clamav_db_timestamp_seconds", "Дата баз сигнатур ClamAV")


# --- отдельные проверки (чистые функции — для тестов) ---


def cert_not_after(pem: bytes) -> float | None:
    """Окончание первого сертификата в PEM; ``None`` — не PEM."""
    from cryptography import x509

    try:
        cert = x509.load_pem_x509_certificate(pem)
    except ValueError:
        return None
    return cert.not_valid_after_utc.timestamp()


def clamav_db_time(reply: str) -> float | None:
    """Дата баз из ответа ``VERSION``: ``ClamAV 1.5.4/27820/Mon Nov 10 07:39:51 2026``."""
    parts = reply.strip().strip("\x00").split("/")
    if len(parts) < 3:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(parts[2].strip() + " +0000")
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.strptime(parts[2].strip(), "%a %b %d %H:%M:%S %Y").replace(
                tzinfo=dt.UTC
            )
        except ValueError:
            return None
    return parsed.timestamp()


async def clamav_version(host: str, port: int, wait: float = 3.0) -> str:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), wait)
    try:
        writer.write(b"zVERSION\x00")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), wait)
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return data.decode("utf-8", "replace")


async def _wal(db: AsyncSession) -> None:
    row = (
        await db.execute(
            text(
                "SELECT extract(epoch FROM last_archived_time), "
                "coalesce(last_failed_time > coalesce(last_archived_time, 'epoch'), false) "
                "FROM pg_stat_archiver"
            )
        )
    ).one()
    if row[0] is not None:
        WAL_LAST.set(float(row[0]))
    WAL_FAILING.set(1 if row[1] else 0)


async def _ad_ca(db: AsyncSession) -> None:
    from estimator.auth.policy import load_auth_mode, read_settings

    if await load_auth_mode(db) != "ad":
        return
    conn = (await read_settings(db, "auth.ad.connection")).get("auth.ad.connection") or {}
    pem = conn.get("ca_cert_pem")
    if pem and (moment := cert_not_after(str(pem).encode())) is not None:
        CERT_NOT_AFTER.labels("ad_ca").set(moment)


def _app_cert(settings: Settings) -> None:
    if not settings.app_tls_cert_path:
        return
    try:
        pem = Path(settings.app_tls_cert_path).read_bytes()
    except OSError:
        return
    if (moment := cert_not_after(pem)) is not None:
        CERT_NOT_AFTER.labels("app").set(moment)


async def _redis_state(redis: Redis) -> None:
    from estimator.auth import ad_sync
    from estimator.security.audit.verify import LAST_RESULT_KEY

    for kind, state in (await ad_sync.last_state(redis)).items():
        if state.get("ok") and state.get("at"):
            at = dt.datetime.fromisoformat(str(state["at"]).replace("Z", "+00:00"))
            AD_SYNC_LAST.labels(kind).set(at.timestamp())
    raw = await redis.get(LAST_RESULT_KEY)
    if raw:
        AUDIT_CHAIN_OK.set(1 if json.loads(raw).get("ok") else 0)


async def _clamav(settings: Settings) -> None:
    try:
        reply = await clamav_version(settings.clamav_host, settings.clamav_port)
    except (OSError, TimeoutError):
        CLAMAV_UP.set(0)
        return
    CLAMAV_UP.set(1 if reply.startswith("ClamAV") else 0)
    if (moment := clamav_db_time(reply)) is not None:
        CLAMAV_DB.set(moment)


async def refresh_once(
    db: AsyncSession, redis: Redis, settings: Settings, now: dt.datetime | None = None
) -> None:
    """Обновить все датчики; сбой одной проверки не мешает остальным."""
    from estimator.admin import health

    async def components() -> None:
        found = await health.report(db, redis, settings)
        for item in found["components"]:
            COMPONENT_UP.labels(item["name"]).set(1 if item["ok"] else 0)

    async def backup() -> None:
        marker = await health.check_backup(settings, now or dt.datetime.now(dt.UTC))
        if marker.checked_at is not None:  # нет метки — нет и времени
            BACKUP_LAST.set(marker.checked_at.timestamp())

    steps: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("components", components),
        ("backup", backup),
        ("wal", lambda: _wal(db)),
        ("ad_ca", lambda: _ad_ca(db)),
        ("redis_state", lambda: _redis_state(redis)),
        ("clamav", lambda: _clamav(settings)),
    ]
    for name, step in steps:
        try:
            async with db.begin_nested():
                await step()
        except Exception as exc:  # noqa: BLE001 — метрики не должны ронять процесс
            log.warning("ops_metrics_failed", step=name, error_type=type(exc).__name__)
            if name == "components":
                # Отдельные проверки report() ловит сам; целиком шаг падает, только когда БД не
                # открывает даже транзакцию. Без этого индикатор db оставался бы прежним (1),
                # и оповещение «БД красная» при остановленной БД не срабатывало (INF-013).
                COMPONENT_UP.labels("db").set(0)
    _app_cert(settings)


class Refresher:
    """Фоновая задача экземпляра API: :func:`refresh_once` каждые :data:`INTERVAL_SECONDS`."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        sessionmaker: Callable[[], async_sessionmaker[AsyncSession]],
        interval: float = INTERVAL_SECONDS,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.sessionmaker = sessionmaker
        self.interval = interval
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:  # pragma: no cover — бесконечный цикл, шаг — refresh_once
        while True:
            # первый замер — через интервал после старта: процесс успевает подняться, а короткие
            # запуски (тесты, разовые команды) не ходят во внешние службы
            await asyncio.sleep(self.interval)
            try:
                async with self.sessionmaker()() as db:
                    await refresh_once(db, self.redis, self.settings)
                    await db.rollback()
            except Exception as exc:  # noqa: BLE001
                log.warning("ops_metrics_loop_failed", error_type=type(exc).__name__)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="ops-metrics")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


__all__ = ["Refresher", "cert_not_after", "clamav_db_time", "refresh_once"]
