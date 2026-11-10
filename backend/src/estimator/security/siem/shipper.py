"""Отправка событий аудита в SIEM (SEC-012; SEC-AUD-05, GAP-09).

Сообщение — syslog RFC 5424: ``<PRI>1 время хост estimator - audit - {JSON}``, где JSON — запись
журнала одной строкой (поля ``audit.record_json`` плюс ``id``, ``category`` и ``hash``). Кадр —
octet-counting RFC 5425 (``<длина> <сообщение>``). Важность: оповещение ИБ (SEC-AUTH-07) —
``alert``, отказ и сбой — ``warning``, остальное — ``info``; facility 13 (log audit).

TLS: сертификат SIEM проверяется по загруженному УЦ (``siem.connection.ca_cert_pem``) и имени
хоста — всегда, отключить нельзя; клиентский сертификат и ключ (mTLS) — если заданы, ключ
хранится зашифрованным (``siem.client_key``). Без УЦ события не отправляются и копятся.

Очередь — записи после курсора ``siem:cursor``. Пачка отправляется одним соединением, курсор
сдвигается после её передачи (сервер принял соединение, см. :func:`_await_acceptance`): при обрыве
пачка уйдёт повторно (SIEM получит дубль с тем
же ``id`` и ``hash``, но не потеряет событие). Больше :data:`MAX_QUEUE` неотправленных —
старейшие пропускаются, в состоянии — «переполнение» (красный индикатор «Состояния системы»).
SIEM выключен — курсор идёт за журналом, очередь не копится. Копия в stdout пишется всегда,
со своим курсором.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import ssl
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TextIO

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.logging import get_logger
from estimator.security.alerts import rules as alert_rules
from estimator.security.audit.catalog import EVENTS

log = get_logger(__name__)

SETTING = "siem.connection"
KEY_SETTING = "siem.client_key"
MAX_QUEUE = 100_000  # SEC-AUD-05
BATCH = 500
MAX_PER_RUN = 20_000
TIMEOUT_SECONDS = 10
ACCEPT_WAIT_SECONDS = 0.3
CURSOR_KEY = "siem:cursor"
STDOUT_CURSOR_KEY = "siem:stdout_cursor"
STATE_KEY = "siem:state"
FACILITY = 13  # log audit (RFC 5424, 6.2.1)
SEVERITY = {"alert": 1, "warning": 4, "info": 6}
APP_NAME = "estimator"

_ROWS = text(
    "SELECT a.id, audit.record_json(a) AS body, encode(a.hash, 'hex') AS hash "
    "FROM audit.audit_log a WHERE a.id > :after ORDER BY a.id LIMIT :limit"
)
_MAX_ID = text("SELECT coalesce(max(id), 0) FROM audit.audit_log")
_BACKLOG = text("SELECT count(*) FROM audit.audit_log WHERE id > :after")
_KEEP_FROM = text(
    "SELECT id FROM audit.audit_log WHERE id > :after ORDER BY id DESC OFFSET :keep LIMIT 1"
)

Db = AsyncConnection | AsyncSession


class SiemError(RuntimeError):
    """SIEM недоступен или не прошёл проверку TLS: события остаются в очереди."""


@dataclass(frozen=True)
class SiemConfig:
    enabled: bool = False
    host: str | None = None
    port: int = 6514
    ca_cert_pem: str | None = None
    client_cert_pem: str | None = None
    client_key_pem: str | None = field(default=None, repr=False)

    @classmethod
    def from_settings(cls, connection: Mapping[str, Any] | None, key: Any = None) -> SiemConfig:
        values = dict(connection or {})
        secret = None
        if key:
            from estimator.security.crypto import get_cipher
            from estimator.security.crypto.aead import is_encrypted_setting

            secret = get_cipher().decrypt_setting(KEY_SETTING, key) if is_encrypted_setting(
                key) else str(key)  # fmt: skip
        return cls(
            enabled=bool(values.get("enabled")),
            host=values.get("host"),
            port=int(values.get("port") or 6514),
            ca_cert_pem=values.get("ca_cert_pem"),
            client_cert_pem=values.get("client_cert_pem"),
            client_key_pem=secret,
        )


async def load_config(db: Db) -> SiemConfig:
    from estimator.auth.policy import read_settings

    values = await read_settings(db, SETTING, KEY_SETTING)
    return SiemConfig.from_settings(values.get(SETTING), values.get(KEY_SETTING))


# --- формат -------------------------------------------------------------------------------


def severity(body: Mapping[str, Any]) -> int:
    event, details = str(body.get("type")), body.get("details") or {}
    spec = EVENTS.get(event)
    if (spec is not None and spec.alert == "always") or alert_rules.triggered(event, details):
        return SEVERITY["alert"]
    return SEVERITY["warning"] if body.get("result") in ("failure", "denied") else SEVERITY["info"]


def record(row_id: int, body: Mapping[str, Any], row_hash: str) -> dict[str, Any]:
    """Запись для SIEM: поля журнала (SEC-AUD-02), ``id``, категория и ``hash``."""
    spec = EVENTS.get(str(body.get("type")))
    return {"id": row_id, **body, "category": spec.category if spec else None, "hash": row_hash}


def format_message(row_id: int, body: Mapping[str, Any], row_hash: str, host: str) -> str:
    """Строка syslog RFC 5424 с JSON записи в MSG."""
    pri = FACILITY * 8 + severity(body)
    stamp = str(body.get("time") or "-")
    payload = json.dumps(record(row_id, body, row_hash), ensure_ascii=False, separators=(",", ":"))
    return f"<{pri}>1 {stamp} {host or '-'} {APP_NAME} - audit - {payload}"


def frame(message: str) -> bytes:
    data = message.encode("utf-8")
    return str(len(data)).encode() + b" " + data


# --- TLS ----------------------------------------------------------------------------------


@contextmanager
def _pem_files(cert: str, key: str) -> Iterator[tuple[str, str]]:
    """Клиентский сертификат и ключ во временных файлах 0600 (``load_cert_chain`` читает файлы)."""
    paths: list[str] = []
    try:
        for content in (cert, key):
            fd, path = tempfile.mkstemp(suffix=".pem")
            paths.append(path)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
        yield paths[0], paths[1]
    finally:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                log.warning("siem_tempfile_cleanup_failed")


def tls_context(config: SiemConfig) -> ssl.SSLContext:
    """Проверка сертификата SIEM по загруженному УЦ и имени хоста — обязательна (GAP-09)."""
    if not config.ca_cert_pem:
        raise SiemError("не загружен сертификат УЦ SIEM")
    context = ssl.create_default_context(cadata=config.ca_cert_pem)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if config.client_cert_pem and config.client_key_pem:
        with _pem_files(config.client_cert_pem, config.client_key_pem) as (cert, key):
            context.load_cert_chain(cert, key)
    return context


Sender = Callable[[SiemConfig, Sequence[bytes]], None]


def _await_acceptance(tls: ssl.SSLSocket) -> None:
    """Дождаться, что сервер принял соединение, до передачи пачки.

    В TLS 1.3 рукопожатие у клиента заканчивается раньше, чем сервер проверит его сертификат:
    отказ (mTLS) приходит уже после отправки данных, и пачка считалась бы доставленной. Короткое
    чтение получает либо отказ, либо, по тайм-ауту, подтверждает, что соединение принято.
    """
    tls.settimeout(ACCEPT_WAIT_SECONDS)
    try:
        if tls.recv(1) == b"":
            raise SiemError("SIEM закрыл соединение")
    except TimeoutError:
        pass
    finally:
        tls.settimeout(TIMEOUT_SECONDS)


def send_tls(config: SiemConfig, frames: Sequence[bytes]) -> None:
    """Отправить кадры одним соединением; любая ошибка — :class:`SiemError`."""
    if not config.host:
        raise SiemError("не задан адрес SIEM")
    try:
        context = tls_context(config)
        with (
            socket.create_connection((config.host, config.port), timeout=TIMEOUT_SECONDS) as raw,
            context.wrap_socket(raw, server_hostname=config.host) as tls,
        ):
            _await_acceptance(tls)
            tls.sendall(b"".join(frames))
    except SiemError:
        raise
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise SiemError(f"{type(exc).__name__}: {exc}") from exc


# --- очередь ------------------------------------------------------------------------------


async def _get_int(redis: Redis, key: str) -> int | None:
    raw = await redis.get(key)
    return int(raw) if raw is not None else None


async def _rows(db: Db, after: int, limit: int) -> list[tuple[int, dict[str, Any], str]]:
    result = await db.execute(_ROWS, {"after": after, "limit": limit})
    return [(int(r[0]), dict(r[1]), str(r[2])) for r in result.all()]


@dataclass
class ShipResult:
    sent: int = 0
    printed: int = 0
    backlog: int = 0
    dropped: int = 0
    error: str | None = None


async def copy_to_stdout(db: Db, redis: Redis, out: TextIO, host: str) -> int:
    """Копия журнала в stdout (SEC-AUD-05): каждое событие один раз, по порядку."""
    after = await _get_int(redis, STDOUT_CURSOR_KEY)
    if after is None:  # первый запуск процесса копирования: начинаем с текущего конца журнала
        after = int(await db.scalar(_MAX_ID) or 0)
        await redis.set(STDOUT_CURSOR_KEY, after)
    printed = 0
    while printed < MAX_PER_RUN and (rows := await _rows(db, after, BATCH)):
        for row_id, body, row_hash in rows:
            out.write(format_message(row_id, body, row_hash, host) + "\n")
        out.flush()
        after = rows[-1][0]
        await redis.set(STDOUT_CURSOR_KEY, after)
        printed += len(rows)
    return printed


async def _trim_overflow(db: Db, redis: Redis, after: int) -> tuple[int, int]:
    """Больше :data:`MAX_QUEUE` в очереди — пропустить старейшие. Вернуть курсор и пропущенные."""
    backlog = int(await db.scalar(_BACKLOG, {"after": after}) or 0)
    if backlog <= MAX_QUEUE:
        return after, 0
    keep_from = await db.scalar(_KEEP_FROM, {"after": after, "keep": MAX_QUEUE})
    new_after = int(keep_from or after)
    await redis.set(CURSOR_KEY, new_after)
    log.error("siem_queue_overflow", dropped=backlog - MAX_QUEUE)
    return new_after, backlog - MAX_QUEUE


async def ship(
    db: Db,
    redis: Redis,
    *,
    sender: Sender = send_tls,
    out: TextIO | None = None,
    host: str | None = None,
) -> ShipResult:
    """Один проход: копия в stdout, затем досылка очереди в SIEM пачками по порядку."""
    host = host or socket.gethostname()
    result = ShipResult(printed=await copy_to_stdout(db, redis, out or sys.stdout, host))
    config = await load_config(db)
    after = await _get_int(redis, CURSOR_KEY) or 0
    if not config.enabled:
        await redis.set(CURSOR_KEY, int(await db.scalar(_MAX_ID) or 0))
        await _save_state(redis, result, enabled=False)
        return result
    after, result.dropped = await _trim_overflow(db, redis, after)
    while result.sent < MAX_PER_RUN and (rows := await _rows(db, after, BATCH)):
        frames = [frame(format_message(i, b, h, host)) for i, b, h in rows]
        try:
            sender(config, frames)
        except SiemError as exc:
            result.error = str(exc)
            log.warning("siem_send_failed", error=result.error, pending_from=after + 1)
            break
        after = rows[-1][0]
        await redis.set(CURSOR_KEY, after)
        result.sent += len(rows)
    result.backlog = int(await db.scalar(_BACKLOG, {"after": after}) or 0)
    await _save_state(redis, result, enabled=True)
    return result


async def _save_state(redis: Redis, result: ShipResult, *, enabled: bool) -> None:
    previous = await state(redis) or {}
    now = dt.datetime.now(dt.UTC).isoformat()
    value = {
        "enabled": enabled,
        "ok": result.error is None,
        "error": result.error,
        "backlog": result.backlog,
        "checked_at": now,
        "last_sent_at": now if result.sent else previous.get("last_sent_at"),
        "overflow_at": now if result.dropped else previous.get("overflow_at"),
        "dropped": result.dropped + int(previous.get("dropped") or 0),
    }
    await redis.set(STATE_KEY, json.dumps(value))


async def state(redis: Redis) -> dict[str, Any] | None:
    """Состояние для «Состояния системы» (компонент ``siem``) и метрики длины очереди.

    ``ok = false`` — последняя отправка не удалась; ``overflow_at`` — когда очередь переполнялась
    (красный индикатор, SEC-AUD-05); ``backlog`` — сколько событий ждёт отправки.
    """
    raw = await redis.get(STATE_KEY)
    return json.loads(raw) if raw else None


class QueueCollector:
    """Метрики Prometheus очереди SIEM (SPEC 18.4: тревога при очереди > 10 000).

    ``estimator_siem_queue_length`` — события, ждущие отправки; ``estimator_siem_up`` — удалась ли
    последняя отправка (1/0); ``estimator_siem_overflow`` — очередь переполнялась (1/0).
    ``reader`` синхронно возвращает :func:`state` (или ``None``, пока отправка не запускалась).
    """

    def __init__(self, reader: Callable[[], dict[str, Any] | None]) -> None:
        self._reader = reader

    def collect(self) -> Iterator[Any]:
        from prometheus_client.core import GaugeMetricFamily

        try:
            current = self._reader()
        except Exception as exc:  # noqa: BLE001 — сбой опроса не должен ронять /metrics
            log.warning("siem_state_read_failed", error_type=type(exc).__name__)
            return
        if not current or not current.get("enabled"):
            return
        for name, doc, value in (
            ("estimator_siem_queue_length", "События аудита, ждущие отправки в SIEM",
             current.get("backlog") or 0),
            ("estimator_siem_up", "Последняя отправка в SIEM удалась (1/0)",
             1 if current.get("ok") else 0),
            ("estimator_siem_overflow", "Очередь SIEM переполнялась (1/0)",
             1 if current.get("overflow_at") else 0),
        ):  # fmt: skip
            metric = GaugeMetricFamily(name, doc)
            metric.add_metric([], value)
            yield metric


def read_state_sync(redis_url: str) -> dict[str, Any] | None:
    """:func:`state` для сборщика метрик (опрос Prometheus синхронный)."""
    from redis import Redis as SyncRedis

    client = SyncRedis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
    try:
        raw = client.get(STATE_KEY)
    finally:
        client.close()
    return json.loads(raw) if raw else None
