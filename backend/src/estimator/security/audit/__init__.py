"""Запись журнала аудита (SEC-004; SEC-AUD-01…03, SEC-AUTH-04, contracts/audit-events.yaml).

* :func:`write` — событие в **той же транзакции**, что и действие: откатилось действие —
  откатилась и запись. Время и хэш-цепочку ставит функция БД ``audit.append`` (DB-009).
* :func:`write_standalone` — событие в **отдельной** транзакции: отказы (403/404, неудачный
  вход, превышение лимита), у которых своей транзакции нет или она откатывается.
* :func:`add_alert_listener` — подписка на события с оповещением ИБ (SEC-AUTH-07); письма
  шлёт :mod:`estimator.security.alerts` (SEC-011). Условия ``alert: when …`` проверяет
  :func:`estimator.security.alerts.rules.triggered`, ``alert=True`` включает оповещение
  принудительно. Слушатели вызываются после commit, сбой слушателя записи не отменяет.

Проверки перед записью: тип события есть в каталоге; ``details`` содержат только ключи схемы
события и общие (``actor``, ``os_user``, ``project_id``); запрещённых ключей
(``forbidden_detail_keys``: пароли, токены, деньги, содержимое оценки) нет; во вложенных
структурах значения секретных ключей заменяются на ``***``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimator.logging import get_logger
from estimator.security.alerts import rules as alert_rules
from estimator.security.audit.catalog import (
    ACTORS,
    COMMON_DETAILS,
    EVENTS,
    FORBIDDEN_DETAIL_KEYS,
    OBJECT_TYPES,
)
from estimator.security.logfilter import REDACTED, is_secret_key

log = get_logger(__name__)

RESULTS = frozenset({"success", "failure", "denied"})

_APPEND = text(
    "SELECT (r).id FROM (SELECT audit.append("
    "p_event_type => :event_type, p_result => CAST(:result AS audit.audit_result), "
    "p_user_id => :user_id, p_login => :login, p_ip => CAST(:ip AS inet), "
    "p_user_agent => :user_agent, p_session_hash => :session_hash, "
    "p_object_type => :object_type, p_object_id => :object_id, "
    "p_details => CAST(:details AS jsonb)) AS r) AS s"
)


class AuditError(ValueError):
    """Событие не соответствует каталогу — ошибка в коде, а не в данных пользователя."""


@dataclass(frozen=True)
class Alert:
    """Событие с оповещением ИБ для слушателей (SEC-AUTH-07)."""

    event_type: str
    audit_id: int
    login: str | None
    ip: str | None
    details: dict[str, Any] = field(default_factory=dict)


AlertListener = Callable[[Alert], Awaitable[None] | None]
_alert_listeners: list[AlertListener] = []


def add_alert_listener(listener: AlertListener) -> None:
    _alert_listeners.append(listener)


def remove_alert_listener(listener: AlertListener) -> None:
    _alert_listeners.remove(listener)


def session_hash(session_id: str) -> bytes:
    """SHA-256 идентификатора сессии: в журнал и в ``sessions.id_hash`` пишется только он."""
    return hashlib.sha256(session_id.encode("ascii")).digest()


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(k): (REDACTED if is_secret_key(k) else _scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def build_details(
    event_type: str,
    details: Mapping[str, Any] | None,
    *,
    actor: str = "user",
    os_user: str | None = None,
    project_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Проверить и собрать ``details`` по каталогу (без записи в БД)."""
    spec = EVENTS.get(event_type)
    if spec is None:
        raise AuditError(f"неизвестное событие аудита: {event_type}")
    if actor not in ACTORS:
        raise AuditError(f"неизвестный actor: {actor}")
    data = dict(details or {})
    unknown = set(data) - spec.details - COMMON_DETAILS
    if unknown:
        raise AuditError(f"{event_type}: ключи details вне каталога: {sorted(unknown)}")
    forbidden = (set(data) & FORBIDDEN_DETAIL_KEYS) - spec.details
    if forbidden:
        raise AuditError(f"{event_type}: запрещённые ключи details: {sorted(forbidden)}")
    if actor != "user":
        data["actor"] = actor
    if os_user is not None:
        data["os_user"] = os_user
    if project_id is not None:
        data["project_id"] = str(project_id)
    return _scrub(data)


async def write(
    session: AsyncSession,
    event_type: str,
    result: str = "success",
    *,
    user_id: UUID | None = None,
    login: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    session_id: str | None = None,
    object_type: str | None = None,
    object_id: UUID | str | None = None,
    details: Mapping[str, Any] | None = None,
    actor: str = "user",
    os_user: str | None = None,
    project_id: UUID | str | None = None,
    alert: bool = False,
) -> int:
    """Записать событие в транзакции ``session``. Возвращает ``audit_log.id``.

    Оповещение ИБ уходит для событий с ``alert: always``, при сработавшем условии ``alert: when …``
    (:func:`~estimator.security.alerts.rules.triggered`) и при ``alert=True``.
    """
    if result not in RESULTS:
        raise AuditError(f"неизвестный результат: {result}")
    if object_type is not None and object_type not in OBJECT_TYPES:
        raise AuditError(f"неизвестный тип объекта: {object_type}")
    data = build_details(event_type, details, actor=actor, os_user=os_user, project_id=project_id)
    row = await session.execute(
        _APPEND,
        {
            "event_type": event_type,
            "result": result,
            "user_id": user_id,
            "login": login,
            "ip": ip,
            "user_agent": user_agent,
            "session_hash": session_hash(session_id) if session_id else None,
            "object_type": object_type,
            "object_id": str(object_id) if object_id is not None else None,
            "details": json.dumps(data, ensure_ascii=False, default=str),
        },
    )
    audit_id = int(row.scalar_one())
    if alert or EVENTS[event_type].alert == "always" or alert_rules.triggered(event_type, data):
        _schedule_alert(session, Alert(event_type, audit_id, login, ip, data))
    return audit_id


async def write_standalone(
    event_type: str,
    result: str = "denied",
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    **kwargs: Any,
) -> int:
    """Записать событие в собственной транзакции (отказы, неудачные входы)."""
    from estimator.db.session import transaction

    async with transaction(sessionmaker) as session:
        return await write(session, event_type, result, **kwargs)


async def write_detached(
    session: AsyncSession, event_type: str, result: str = "failure", **kwargs: Any
) -> int | None:
    """Записать событие в отдельной транзакции на том же подключении, что и ``session``.

    Для отказов внутри транзакции запроса: запрос ответит ошибкой и откатится, а событие
    останется. Сбой записи логируется и не меняет ответ пользователю.
    """
    from estimator.db.session import transaction

    try:
        maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
        async with transaction(maker) as own:
            return await write(own, event_type, result, **kwargs)
    except AuditError:
        raise
    except Exception:
        log.exception("audit_write_detached_failed", event_type=event_type)
        return None


def _schedule_alert(session: AsyncSession, alert: Alert) -> None:
    from estimator.db.session import after_commit

    async def notify() -> None:
        for listener in list(_alert_listeners):
            try:
                outcome = listener(alert)
                if outcome is not None:
                    await outcome
            except Exception:  # сбой оповещения не отменяет записанное событие
                log.exception("audit_alert_listener_failed", event_type=alert.event_type)

    after_commit(session, notify)
