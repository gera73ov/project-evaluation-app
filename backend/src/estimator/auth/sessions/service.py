"""Серверные сессии (AUTH-002; FR-SESS-01…03, FR-AUTH-LOC-02, BR-ROLE-01, ARCH-05).

Хранение
    Идентификатор — 256 бит (``secrets.token_urlsafe(32)``), есть только в cookie и в ключе
    Redis ``session:{sha256 hex}`` (хэш с полями :class:`SessionRecord`). Индекс сессий
    пользователя — ``usessions:{user_id}`` (ZSET по времени создания). Копия метаданных —
    строка ``sessions`` с ``id_hash`` (contracts/db/schema.md): список сессий (FR-SESS-04) и аудит.
    Источник истины на запросе — Redis: потеря Redis означает повторный вход (ARCH-05).

Сроки
    Бездействие проверяется по ``last_seen_at`` (самый короткий тайм-аут ролей на момент
    входа, BR-ROLE-01), абсолютный срок — по ``absolute_at``; TTL ключа равен остатку
    абсолютного срока, поэтому по ключу видно, *почему* сессия истекла (аудит
    ``auth.session.expired``). Сессия до подключения TOTP — не дольше 15 минут (FR-2FA-04).
    Запросы с ``X-Background: 1`` активность не продлевают; ``last_seen_at`` в БД переносится
    не чаще раза в минуту.

Смена идентификатора (FR-SESS-03): новая запись и строка, старая строка закрывается с
``revoke_reason = 'superseded'``. Лимит сессий: при превышении закрывается самая старая.

Отзыв: по сессии, по пользователю, «все, кроме текущей». Слушатели
:func:`add_session_ended_listener` (закрытие WebSocket, RT) вызываются после commit транзакции.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.auth.policy import PRE_MFA_SECONDS, SessionPolicy
from estimator.db.enums import SystemRole
from estimator.logging import get_logger
from estimator.security import audit

log = get_logger(__name__)

KEY_PREFIX = "session:"
USER_INDEX_PREFIX = "usessions:"
DB_TOUCH_INTERVAL = 60  # секунд: перенос last_seen_at в БД не чаще (contracts/db/schema.md)
USER_AGENT_MAX = 512


class RevokeReason(StrEnum):
    """``sessions.revoke_reason`` (contracts/db/schema.md, раздел 4)."""

    LOGOUT = "logout"
    EXPIRED = "expired"
    USER_REVOKED = "user_revoked"
    BLOCKED = "blocked"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105  # nosec B105 — причина, не пароль
    AD_CHECK = "ad_check"
    MODE_SWITCH = "mode_switch"
    SUPERSEDED = "superseded"


class ExpiryReason(StrEnum):
    """``details.reason`` события ``auth.session.expired``."""

    IDLE = "idle"
    ABSOLUTE = "absolute"
    PRE_MFA_LIMIT = "pre_mfa_limit"


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def id_hash(session_id: str) -> bytes:
    """SHA-256 идентификатора: ключ строки ``sessions`` и поле ``session_hash`` аудита."""
    return hashlib.sha256(session_id.encode("ascii")).digest()


def _key(session_id: str) -> str:
    return KEY_PREFIX + id_hash(session_id).hex()


def _user_index(user_id: uuid.UUID | str) -> str:
    return f"{USER_INDEX_PREFIX}{user_id}"


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _ts(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None


@dataclass(frozen=True)
class SessionRecord:
    """Содержимое ``session:{hash}``; время — секунды Unix."""

    user_id: str
    created_at: float
    last_seen_at: float
    absolute_at: float
    idle_seconds: int
    roles: tuple[str, ...] = ()
    mfa_passed: bool = False
    enrollment_required: bool = False
    step_up_until: float | None = None
    csrf: str = ""
    ip: str = ""
    db_seen_at: float = 0.0

    @property
    def user_uuid(self) -> uuid.UUID:
        return uuid.UUID(self.user_id)

    def expiry(self, now: float) -> ExpiryReason | None:
        if now >= self.absolute_at:
            return ExpiryReason.PRE_MFA_LIMIT if self.enrollment_required else ExpiryReason.ABSOLUTE
        if now >= self.last_seen_at + self.idle_seconds:
            return ExpiryReason.IDLE
        return None

    def expires_in(self, now: float) -> int:
        """Секунд до истечения (бездействие или абсолютный срок) — для диалога продления."""
        return max(0, int(min(self.absolute_at, self.last_seen_at + self.idle_seconds) - now))

    def to_redis(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            if isinstance(value, bool):
                out[f.name] = "1" if value else "0"
            elif isinstance(value, tuple):
                out[f.name] = ",".join(value)
            else:
                out[f.name] = str(value)
        return out

    @classmethod
    def from_redis(cls, raw: dict[Any, Any]) -> SessionRecord:
        data = {_text(k): _text(v) for k, v in raw.items()}
        step_up = data.get("step_up_until")
        return cls(
            user_id=data["user_id"],
            created_at=float(data["created_at"]),
            last_seen_at=float(data["last_seen_at"]),
            absolute_at=float(data["absolute_at"]),
            idle_seconds=int(data["idle_seconds"]),
            roles=tuple(r for r in data.get("roles", "").split(",") if r),
            mfa_passed=data.get("mfa_passed") == "1",
            enrollment_required=data.get("enrollment_required") == "1",
            step_up_until=float(step_up) if step_up else None,
            csrf=data.get("csrf", ""),
            ip=data.get("ip", ""),
            db_seen_at=float(data.get("db_seen_at", 0) or 0),
        )


@dataclass(frozen=True)
class LoadedSession:
    """Результат :meth:`SessionService.load`: запись либо причина, по которой её нет."""

    record: SessionRecord | None
    expired: ExpiryReason | None = None


@dataclass(frozen=True)
class SessionInfo:
    """Строка списка «Мои сессии» (FR-SESS-04)."""

    session_hash: bytes
    record: SessionRecord
    user_agent: str | None = None


@dataclass(frozen=True)
class SessionEnded:
    """Событие для RT: сессия завершена (истекла или отозвана)."""

    user_id: uuid.UUID
    session_hash: bytes
    reason: str


SessionEndedListener = Callable[[SessionEnded], Awaitable[None] | None]
_ended_listeners: list[SessionEndedListener] = []


def add_session_ended_listener(listener: SessionEndedListener) -> None:
    _ended_listeners.append(listener)


def remove_session_ended_listener(listener: SessionEndedListener) -> None:
    _ended_listeners.remove(listener)


async def _notify_ended(events: list[SessionEnded]) -> None:
    for event in events:
        for listener in list(_ended_listeners):
            try:
                outcome = listener(event)
                if outcome is not None:
                    await outcome
            except Exception:  # сбой слушателя не отменяет отзыв
                log.exception("session_ended_listener_failed", reason=event.reason)


_INSERT = text(
    "INSERT INTO sessions (id_hash, user_id, created_at, last_seen_at, expires_at, ip, "
    "user_agent, mfa_passed) VALUES (:id_hash, :user_id, :created_at, :created_at, "
    ":expires_at, CAST(:ip AS inet), :user_agent, :mfa_passed)"
)
_REVOKE = text(
    "UPDATE sessions SET revoked_at = now(), revoke_reason = :reason "
    "WHERE id_hash = ANY(:hashes) AND revoked_at IS NULL"
)
_REVOKE_USER = text(
    "UPDATE sessions SET revoked_at = now(), revoke_reason = :reason "
    "WHERE user_id = :user_id AND revoked_at IS NULL AND id_hash <> ALL(:keep) "
    "RETURNING id_hash"
)
_USER_AGENTS = text("SELECT id_hash, user_agent FROM sessions WHERE id_hash = ANY(:hashes)")
_TOUCH = text("UPDATE sessions SET last_seen_at = :ts WHERE id_hash = :id_hash")
_SET_FLAGS = text(
    "UPDATE sessions SET mfa_passed = :mfa_passed, step_up_until = :step_up_until "
    "WHERE id_hash = :id_hash"
)


class SessionService:
    """Операции над сессиями; ``clock`` подменяется в тестах."""

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    def now(self) -> float:
        """Текущее время часов сервиса (секунды Unix)."""
        return self._clock()

    # --- создание и смена идентификатора ---

    async def create(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        roles: Collection[SystemRole | str],
        policy: SessionPolicy,
        *,
        ip: str,
        user_agent: str | None = None,
        mfa_passed: bool = False,
        enrollment_required: bool = False,
    ) -> tuple[str, SessionRecord]:
        """Новая сессия после успешного входа. Возвращает идентификатор (в cookie) и запись.

        Если превышен лимит ``max_sessions``, самые старые сессии закрываются (``superseded``).
        """
        now = self._clock()
        lifetime = PRE_MFA_SECONDS if enrollment_required else policy.absolute_seconds
        record = SessionRecord(
            user_id=str(user_id),
            created_at=now,
            last_seen_at=now,
            absolute_at=now + min(lifetime, policy.absolute_seconds),
            idle_seconds=policy.idle_seconds(roles),
            roles=tuple(sorted(str(r) for r in roles)),
            mfa_passed=mfa_passed,
            enrollment_required=enrollment_required,
            csrf=secrets.token_urlsafe(32),
            ip=ip,
            db_seen_at=now,
        )
        session_id = new_session_id()
        await self._store(session_id, record)
        await db.execute(
            _INSERT,
            {
                "id_hash": id_hash(session_id),
                "user_id": user_id,
                "created_at": _ts(now),
                "expires_at": _ts(record.absolute_at),
                "ip": ip,
                "user_agent": (user_agent or "")[:USER_AGENT_MAX] or None,
                "mfa_passed": mfa_passed,
            },
        )
        if policy.max_sessions is not None:
            await self._enforce_limit(db, user_id, policy.max_sessions, keep=session_id)
        return session_id, record

    async def rotate(
        self,
        db: AsyncSession,
        session_id: str,
        record: SessionRecord,
        *,
        user_agent: str | None = None,
        **changes: Any,
    ) -> tuple[str, SessionRecord]:
        """Сменить идентификатор (FR-SESS-03): например, после TOTP ``mfa_passed=True``."""
        now = self._clock()
        new_record = replace(record, db_seen_at=now, **changes)
        new_id = new_session_id()
        await self._store(new_id, new_record)
        await self._drop(session_id, record.user_id)
        await db.execute(
            _REVOKE, {"hashes": [id_hash(session_id)], "reason": RevokeReason.SUPERSEDED.value}
        )
        await db.execute(
            _INSERT,
            {
                "id_hash": id_hash(new_id),
                "user_id": record.user_uuid,
                "created_at": _ts(now),
                "expires_at": _ts(new_record.absolute_at),
                "ip": new_record.ip or "0.0.0.0",  # noqa: S104  # nosec B104 — адрес неизвестен
                "user_agent": (user_agent or "")[:USER_AGENT_MAX] or None,
                "mfa_passed": new_record.mfa_passed,
            },
        )
        if new_record.step_up_until is not None:
            await self._write_flags(db, new_id, new_record)
        return new_id, new_record

    async def update(
        self, db: AsyncSession, session_id: str, record: SessionRecord, **changes: Any
    ) -> SessionRecord:
        """Изменить поля без смены идентификатора (например, ``step_up_until``)."""
        new_record = replace(record, **changes)
        await self._store(session_id, new_record)
        await self._write_flags(db, session_id, new_record)
        return new_record

    # --- проверка на запросе ---

    async def load(self, session_id: str) -> LoadedSession:
        """Запись сессии; истёкшая удаляется из Redis, ``expired`` содержит причину."""
        if not session_id or len(session_id) > 128:
            return LoadedSession(None)
        raw = await self._redis.hgetall(_key(session_id))
        if not raw:
            return LoadedSession(None)
        record = SessionRecord.from_redis(raw)
        reason = record.expiry(self._clock())
        if reason is not None:
            await self._drop(session_id, record.user_id)
            return LoadedSession(record, reason)
        return LoadedSession(record)

    async def touch(
        self, db: AsyncSession, session_id: str, record: SessionRecord, *, background: bool
    ) -> SessionRecord:
        """Отметить активность. Фоновые запросы (``X-Background: 1``) не продлевают сессию."""
        if background:
            return record
        now = self._clock()
        changes: dict[str, Any] = {"last_seen_at": now}
        sync_db = now - record.db_seen_at >= DB_TOUCH_INTERVAL
        if sync_db:
            changes["db_seen_at"] = now
        await self._redis.hset(_key(session_id), mapping={k: str(v) for k, v in changes.items()})
        if sync_db:
            await db.execute(_TOUCH, {"ts": _ts(now), "id_hash": id_hash(session_id)})
        return replace(record, **changes)

    # --- отзыв ---

    async def end(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: uuid.UUID | str,
        reason: RevokeReason,
    ) -> None:
        """Завершить одну сессию (выход, истечение)."""
        from estimator.db.session import after_commit

        hashed = id_hash(session_id)
        await self._drop(session_id, user_id)
        await db.execute(_REVOKE, {"hashes": [hashed], "reason": reason.value})
        event = SessionEnded(uuid.UUID(str(user_id)), hashed, reason.value)
        after_commit(db, lambda: _notify_ended([event]))

    async def revoke_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        reason: RevokeReason,
        *,
        except_session_id: str | None = None,
    ) -> int:
        """Завершить все сессии пользователя (или все, кроме текущей). Возвращает их число."""
        from estimator.db.session import after_commit

        keep = [id_hash(except_session_id)] if except_session_id else []
        index = _user_index(user_id)
        members = [m.decode() if isinstance(m, bytes) else m
                   for m in await self._redis.zrange(index, 0, -1)]  # fmt: skip
        doomed = [m for m in members if bytes.fromhex(m) not in keep]
        if doomed:
            await self._redis.delete(*(KEY_PREFIX + m for m in doomed))
            await self._redis.zrem(index, *doomed)
        rows = (
            (
                await db.execute(
                    _REVOKE_USER, {"user_id": user_id, "reason": reason.value, "keep": keep}
                )
            )
            .scalars()
            .all()
        )
        hashes = {bytes(h) for h in rows} | {bytes.fromhex(m) for m in doomed}
        events = [SessionEnded(user_id, h, reason.value) for h in sorted(hashes)]
        if events:
            after_commit(db, lambda: _notify_ended(events))
        return len(hashes)

    async def end_by_hash(
        self, db: AsyncSession, user_id: uuid.UUID, hashed: bytes, reason: RevokeReason
    ) -> bool:
        """Завершить одну свою сессию по хэшу (список «Мои сессии», FR-SESS-04).

        Чужой или неизвестный хэш — ``False``: в индексе пользователя его нет.
        """
        from estimator.db.session import after_commit

        member = hashed.hex()
        if await self._redis.zscore(_user_index(user_id), member) is None:
            return False
        await self._redis.delete(KEY_PREFIX + member)
        await self._redis.zrem(_user_index(user_id), member)
        await db.execute(_REVOKE, {"hashes": [hashed], "reason": reason.value})
        event = SessionEnded(user_id, hashed, reason.value)
        after_commit(db, lambda: _notify_ended([event]))
        return True

    async def list_user(self, db: AsyncSession, user_id: uuid.UUID) -> list[SessionInfo]:
        """Живые сессии пользователя, от новых к старым: время и IP — из Redis, браузер — из БД."""
        infos: list[SessionInfo] = []
        for hashed in await self.active_hashes(user_id):
            raw = await self._redis.hgetall(KEY_PREFIX + hashed.hex())
            if not raw:
                continue
            record = SessionRecord.from_redis(raw)
            if record.expiry(self._clock()) is not None:
                continue
            infos.append(SessionInfo(hashed, record))
        agents = dict(
            (
                await db.execute(
                    _USER_AGENTS, {"hashes": [i.session_hash for i in infos]}
                )
            ).all()
        ) if infos else {}  # fmt: skip
        return [
            replace(i, user_agent=agents.get(i.session_hash))
            for i in sorted(infos, key=lambda i: i.record.created_at, reverse=True)
        ]

    async def active_hashes(self, user_id: uuid.UUID | str) -> list[bytes]:
        """Хэши живых сессий пользователя в Redis, от старых к новым."""
        members = await self._redis.zrange(_user_index(user_id), 0, -1)
        out = []
        for m in members:
            hex_hash = m.decode() if isinstance(m, bytes) else m
            if await self._redis.exists(KEY_PREFIX + hex_hash):
                out.append(bytes.fromhex(hex_hash))
        return out

    # --- внутреннее ---

    async def _store(self, session_id: str, record: SessionRecord) -> None:
        key = _key(session_id)
        ttl = max(1, int(record.absolute_at - self._clock()) + 1)
        index = _user_index(record.user_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.hset(key, mapping=record.to_redis())
            pipe.expire(key, ttl)
            pipe.zadd(index, {id_hash(session_id).hex(): record.created_at})
            pipe.expire(index, ttl, gt=True)
            pipe.expire(index, ttl, nx=True)
            await pipe.execute()

    async def _drop(self, session_id: str, user_id: uuid.UUID | str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(_key(session_id))
            pipe.zrem(_user_index(user_id), id_hash(session_id).hex())
            await pipe.execute()

    async def _write_flags(self, db: AsyncSession, session_id: str, record: SessionRecord) -> None:
        await db.execute(
            _SET_FLAGS,
            {
                "id_hash": id_hash(session_id),
                "mfa_passed": record.mfa_passed,
                "step_up_until": _ts(record.step_up_until),
            },
        )

    async def _enforce_limit(
        self, db: AsyncSession, user_id: uuid.UUID, limit: int, *, keep: str
    ) -> None:
        from estimator.db.session import after_commit

        active = await self.active_hashes(user_id)
        excess = len(active) - limit
        if excess <= 0:
            return
        keep_hash = id_hash(keep)
        doomed = [h for h in active if h != keep_hash][:excess]
        index = _user_index(user_id)
        await self._redis.delete(*(KEY_PREFIX + h.hex() for h in doomed))
        await self._redis.zrem(index, *(h.hex() for h in doomed))
        await db.execute(_REVOKE, {"hashes": doomed, "reason": RevokeReason.SUPERSEDED.value})
        events = [SessionEnded(user_id, h, "session_limit") for h in doomed]
        after_commit(db, lambda: _notify_ended(events))
        await audit.write(
            db,
            "auth.sessions.terminated",
            user_id=user_id,
            object_type="user",
            object_id=user_id,
            details={"count": len(doomed), "reason": "session_limit"},
            actor="system",
        )
        log.info("session_limit_enforced", user_id=str(user_id), closed=len(doomed))
