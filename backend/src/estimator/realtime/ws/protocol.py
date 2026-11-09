"""Команды клиента и ответы сервера по контракту RT-001 (``$defs.ClientCommand``, ``ServerReply``).

Разбор строгий: неизвестная операция, лишний или недостающий ключ, неверный тип — ответ
``error`` с кодом ``VALIDATION_FAILED`` (contracts/ws-events.md). Ключи и обязательность берутся
из схемы, форматы (UUID, целое ≥ 0, поле захвата) проверяются здесь.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import cache
from typing import Any

from estimator.realtime.bus.contract import schema
from estimator.realtime.locks.iface import LOCK_FIELDS

#: Одно сообщение WebSocket — не больше 64 КБ (SEC-WEB-08)
MAX_MESSAGE_BYTES = 64 * 1024
REQ_ID_MAX = 64
HEARTBEAT_LOCKS_MAX = 20

# Коды закрытия соединения (contracts/ws-events.md)
CLOSE_NORMAL = 1000
CLOSE_UNSUPPORTED = 1003  # двоичный кадр вместо JSON
CLOSE_TOO_BIG = 1009  # сообщение больше 64 КБ
CLOSE_RESTART = 1012  # перезапуск экземпляра API или переподключение к Redis
CLOSE_OVERLOADED = 1013  # клиент не успевает принимать события
CLOSE_SESSION_ENDED = 4401
CLOSE_ORIGIN = 4403
CLOSE_RATE_LIMITED = 4429


class CommandError(Exception):
    """Команда отклонена: ответ ``error`` с кодом из contracts/errors.yaml."""

    def __init__(self, code: str, detail: str | None = None, **extensions: Any) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.extensions = extensions


@dataclass(frozen=True)
class Command:
    op: str
    req_id: str | None
    args: dict[str, Any]

    def uuid(self, key: str) -> uuid.UUID:
        return uuid.UUID(self.args[key])


@cache
def _ops() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """``{op: (допустимые ключи, обязательные ключи)}`` из ``$defs.ClientCommand``."""
    out: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for variant in schema()["$defs"]["ClientCommand"]["oneOf"]:
        op = variant["properties"]["op"]["const"]
        out[op] = (frozenset(variant["properties"]), frozenset(variant.get("required", [])))
    return out


def _invalid(detail: str) -> CommandError:
    return CommandError("VALIDATION_FAILED", detail)


def _check_uuid(value: Any, key: str) -> None:
    if not isinstance(value, str):
        raise _invalid(f"{key}: нужен UUID строкой")
    try:
        uuid.UUID(value)
    except ValueError:
        raise _invalid(f"{key}: нужен UUID строкой") from None


def _check_field(value: Any, key: str) -> None:
    if value not in LOCK_FIELDS:
        raise _invalid(f"{key}: допустимы {', '.join(sorted(LOCK_FIELDS))}")


def _check_value(op: str, key: str, value: Any) -> None:
    if key in ("project_id", "node_id"):
        _check_uuid(value, key)
    elif key == "field":
        _check_field(value, key)
    elif key == "since":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _invalid("since: нужно целое ≥ 0")
    elif key == "force":
        if not isinstance(value, bool):
            raise _invalid("force: нужно true или false")
    elif key == "locks":
        if not isinstance(value, list) or len(value) > HEARTBEAT_LOCKS_MAX:
            raise _invalid(f"locks: нужен список не длиннее {HEARTBEAT_LOCKS_MAX}")
        for item in value:
            if not isinstance(item, dict) or set(item) != {"node_id", "field"}:
                raise _invalid("locks: элемент — {node_id, field}")
            _check_uuid(item["node_id"], "locks.node_id")
            _check_field(item["field"], "locks.field")


def parse_command(raw: str) -> Command:
    """Разобрать текст кадра; иначе :class:`CommandError` (``req_id`` в ответ — если удалось)."""
    try:
        message = json.loads(raw)
    except ValueError:
        raise _invalid("сообщение не является JSON") from None
    if not isinstance(message, dict):
        raise _invalid("сообщение — объект JSON")
    op = message.get("op")
    req_id = message.get("req_id")
    if req_id is not None and (not isinstance(req_id, str) or len(req_id) > REQ_ID_MAX):
        raise CommandError(
            "VALIDATION_FAILED", f"req_id: строка не длиннее {REQ_ID_MAX}", op=op, req_id=None
        )
    spec = _ops().get(op) if isinstance(op, str) else None
    if spec is None:
        raise CommandError("VALIDATION_FAILED", "неизвестная операция", op=op, req_id=req_id)
    allowed, required = spec
    try:
        if extra := sorted(set(message) - allowed):
            raise _invalid(f"лишние ключи: {', '.join(extra)}")
        if missing := sorted(required - set(message)):
            raise _invalid(f"нет ключей: {', '.join(missing)}")
        for key, value in message.items():
            _check_value(op, key, value)
    except CommandError as exc:
        exc.extensions.update(op=op, req_id=req_id)
        raise
    args = {k: v for k, v in message.items() if k not in ("op", "req_id")}
    return Command(op=op, req_id=req_id, args=args)


def ack(op: str, req_id: str | None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    reply: dict[str, Any] = {"type": "ack", "op": op}
    if req_id is not None:
        reply["req_id"] = req_id
    if result is not None:
        reply["result"] = result
    return reply


#: Поля-расширения ответа ``error`` (``$defs.ServerReply``)
_ERROR_EXTENSIONS = ("locked_by", "expires_at", "project_status", "retry_after")


def error(
    op: str | None, req_id: str | None, code: str, detail: str | None = None, **extensions: Any
) -> dict[str, Any]:
    reply: dict[str, Any] = {"type": "error", "code": code}
    if isinstance(op, str):
        reply["op"] = op
    if isinstance(req_id, str):
        reply["req_id"] = req_id
    if detail:
        reply["detail"] = detail
    for key in _ERROR_EXTENSIONS:
        if extensions.get(key) is not None:
            reply[key] = extensions[key]
    return reply


def command_error(exc: CommandError) -> dict[str, Any]:
    ext = dict(exc.extensions)
    op, req_id = ext.pop("op", None), ext.pop("req_id", None)
    return error(op, req_id, exc.code, exc.detail, **ext)
