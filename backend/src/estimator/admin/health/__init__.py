"""«Состояние системы» (ADM-003; SPEC FR-SA-07, SEC-AUD-03, SEC-AUD-04, SEC-AUD-05, SEC-AUTH-07,
FR-AUTH-AD-08, 18.4; 15.2 ``GET /system/health``).

Версии приложения и схемы БД и по компоненту — ``ok`` (зелёный/красный) и пояснение:

* ``db`` — запрос к PostgreSQL; ``redis`` — PING;
* ``smtp`` — сервер настроен и принимает TCP-соединение; красный и при недоставленном за 30 дней
  оповещении ИБ (SEC-AUTH-07, :func:`notify.last_undelivered`);
* ``ldap`` — в режиме «Приложение» не используется (зелёный); в режиме AD — TCP-соединение
  хотя бы с одним контроллером. Предупреждение «AD-проверка пропущена» добавит AUTH-016;
* ``siem`` — состояние отправки (SEC-012): выключено — зелёный; ошибка или переполнение очереди —
  красный;
* ``queue`` — брокер Celery доступен; в пояснении — задач в очередях;
* ``backup`` — файл-метка скрипта бэкапа не старше 26 часов (18.4);
* ``audit_chain`` — последняя проверка цепочки аудита пройдена (SEC-AUD-03);
* ``audit_purge`` — нет записей аудита старше срока хранения с запасом в месяц (SEC-AUD-04).

Неизвестное состояние (проверка ещё не выполнялась, метки нет) — красный: индикаторы
безопасности не должны быть зелёными «по умолчанию». Каждая проверка ограничена тайм-аутом и не
роняет ответ: сбой — красный индикатор без текста исключения.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.settings import schema
from estimator.auth.policy import load_auth_mode, read_settings
from estimator.config import Settings
from estimator.db.models.audit import AuditLog
from estimator.logging import get_logger

log = get_logger(__name__)

BACKUP_MAX_AGE = dt.timedelta(hours=26)  # 18.4: «бэкап старше 26 часов»
PURGE_GRACE_MONTHS = 1
TIMEOUT_SECONDS = 3.0


@dataclass
class Component:
    name: str
    ok: bool
    detail: str | None = None
    checked_at: dt.datetime | None = None

    def out(self, now: dt.datetime) -> dict[str, Any]:
        at = self.checked_at or now
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "checked_at": at.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        }


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _fmt(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%d.%m.%Y %H:%M UTC")


async def tcp_reachable(host: str, port: int) -> bool:
    """Принимает ли ``host:port`` TCP-соединение за ``TIMEOUT_SECONDS`` (без обмена данными)."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT_SECONDS)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


def queue_lengths(settings: Settings) -> dict[str, int]:
    from estimator.jobs.celery_app import queue_lengths as lengths

    return lengths(settings)


# --- проверки ---


async def check_db(db: AsyncSession) -> Component:
    await db.execute(text("SELECT 1"))
    return Component("db", True)


async def check_redis(redis: Redis) -> Component:
    await redis.ping()
    return Component("redis", True)


async def check_smtp(db: AsyncSession, redis: Redis) -> Component:
    from estimator.security.alerts import notify

    server = (await read_settings(db, "smtp.server")).get("smtp.server")
    server = {**schema.default("smtp.server"), **(server or {})}
    if not (server.get("host") and server.get("from_address")):
        return Component("smtp", False, "SMTP не настроен: ссылки выдаются на экран")
    if not await tcp_reachable(server["host"], int(server["port"])):
        return Component("smtp", False, f"Сервер {server['host']}:{server['port']} недоступен")
    lost = await notify.last_undelivered(redis)
    if lost:
        at = _parse_time(lost.get("at"))
        when = f" ({_fmt(at)})" if at else ""
        return Component("smtp", False, f"Оповещение ИБ не доставлено{when}", at)
    return Component("smtp", True)


async def check_ldap(db: AsyncSession, redis: Redis | None = None) -> Component:
    if await load_auth_mode(db) != "ad":
        return Component("ldap", True, "Режим «Приложение»: AD не используется")
    raw = (await read_settings(db, "auth.ad.connection")).get("auth.ad.connection") or {}
    controllers = raw.get("controllers") or []
    if not controllers:
        return Component("ldap", False, "Контроллеры AD не заданы")
    reachable = False
    for item in controllers:
        if await tcp_reachable(item["host"], int(item["port"])):
            reachable = True
            break
    if not reachable:
        return Component("ldap", False, "Ни один контроллер AD не отвечает")
    if redis is not None:  # AUTH-016: проверка пользователей пропущена, потому что AD не ответил
        from estimator.auth import ad_sync

        for state in (await ad_sync.last_state(redis)).values():
            if not state.get("ok"):
                at = _parse_time(state.get("at"))
                when = f" ({_fmt(at)})" if at else ""
                return Component("ldap", False, f"Проверка пользователей в AD пропущена{when}", at)
    return Component("ldap", True)


async def check_siem(redis: Redis) -> Component:
    from estimator.security.siem import shipper

    current = await shipper.state(redis)
    if current is None:
        return Component("siem", True, "Передача в SIEM не выполнялась")
    at = _parse_time(current.get("checked_at"))
    if not current.get("enabled"):
        return Component("siem", True, "Передача в SIEM выключена", at)
    overflow = _parse_time(current.get("overflow_at"))
    if overflow is not None:
        return Component("siem", False, f"Очередь SIEM переполнялась ({_fmt(overflow)})", at)
    if not current.get("ok"):
        return Component("siem", False, "Последняя отправка в SIEM не удалась", at)
    return Component("siem", True, f"Ждут отправки: {int(current.get('backlog') or 0)}", at)


async def check_queue(settings: Settings) -> Component:
    lengths = await asyncio.to_thread(queue_lengths, settings)
    return Component("queue", True, f"Задач в очереди: {sum(lengths.values())}")


async def check_backup(settings: Settings, now: dt.datetime) -> Component:
    path = settings.backup_marker_path
    try:
        content = await asyncio.to_thread(_read_marker, path)
    except OSError:
        return Component("backup", False, "Нет данных о резервной копии")
    at = _parse_time(content[0]) or dt.datetime.fromtimestamp(content[1], dt.UTC)
    if now - at > BACKUP_MAX_AGE:
        return Component("backup", False, f"Последняя копия {_fmt(at)}: старше 26 часов", at)
    return Component("backup", True, f"Последняя копия {_fmt(at)}", at)


def _read_marker(path: str) -> tuple[str, float]:
    with open(path, encoding="utf-8") as handle:
        first = handle.readline().strip()
    return first, os.stat(path).st_mtime


async def check_audit_chain(redis: Redis) -> Component:
    from estimator.security.audit.verify import LAST_RESULT_KEY

    raw = await redis.get(LAST_RESULT_KEY)
    if not raw:
        return Component("audit_chain", False, "Проверка цепочки аудита ещё не выполнялась")
    result = json.loads(raw)
    at = _parse_time(result.get("finished_at"))
    if not result.get("ok"):
        broken = result.get("first_broken_id")
        return Component("audit_chain", False, f"Цепочка аудита нарушена (запись {broken})", at)
    return Component(
        "audit_chain", True, f"Проверено записей: {int(result.get('checked') or 0)}", at
    )


async def check_audit_purge(db: AsyncSession, now: dt.datetime) -> Component:
    periods = (await read_settings(db, "retention.periods")).get("retention.periods") or {}
    months = int({**schema.default("retention.periods"), **periods}["audit_months"])
    oldest = await db.scalar(select(func.min(AuditLog.ts)))
    limit = now - dt.timedelta(days=31 * (months + PURGE_GRACE_MONTHS))
    if oldest is not None and oldest < limit:
        return Component(
            "audit_purge", False, f"Есть записи старше {months} мес.: удаление просрочено"
        )
    return Component("audit_purge", True, f"Срок хранения аудита — {months} мес.")


# --- сборка ---


async def _guard(name: str, check: Callable[[], Awaitable[Component]]) -> Component:
    try:
        return await asyncio.wait_for(check(), TIMEOUT_SECONDS + 1)
    except Exception as exc:  # noqa: BLE001 — сбой проверки = красный индикатор
        log.warning("system_health_check_failed", check=name, error_type=type(exc).__name__)
        return Component(name, False, "Недоступно")


async def schema_version(db: AsyncSession) -> str:
    try:
        async with db.begin_nested():
            value = await db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # noqa: BLE001 — таблицы нет (БД создана без миграций)
        return "unknown"
    return str(value or "unknown")


async def report(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    # проверки БД идут по очереди: у сессии одно соединение
    db_checks: list[tuple[str, Callable[[], Awaitable[Component]]]] = [
        ("db", lambda: check_db(db)),
        ("smtp", lambda: check_smtp(db, redis)),
        ("ldap", lambda: check_ldap(db, redis)),
        ("audit_purge", lambda: check_audit_purge(db, now)),
    ]
    found = {name: await _guard(name, check) for name, check in db_checks}
    other = {
        "redis": lambda: check_redis(redis),
        "siem": lambda: check_siem(redis),
        "queue": lambda: check_queue(settings),
        "backup": lambda: check_backup(settings, now),
        "audit_chain": lambda: check_audit_chain(redis),
    }
    results = await asyncio.gather(*(_guard(n, c) for n, c in other.items()))
    found.update({c.name: c for c in results})
    order = ("db", "redis", "smtp", "ldap", "siem", "queue", "backup", "audit_chain", "audit_purge")
    return {
        "app_version": settings.app_version,
        "schema_version": await schema_version(db),
        "components": [found[name].out(now) for name in order],
    }
