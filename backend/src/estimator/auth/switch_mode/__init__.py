"""Переход «Приложение → AD» (AUTH-018; FR-AUTH-SW-01, Q-20, C-13, D-22, 11.2 №2, SEC-AUTH-07;
``POST /system/auth/switch-mode``, ``/switch-mode/resolve``, ``GET /switch-mode/last``).

* Отчёт (``dry_run``): каждая локальная учётка, кроме суперадминистраторов (они всегда локальные,
  FR-SA-03) и анонимизированных, ищется в AD **только по логину** без учёта регистра:
  «сопоставлено однозначно» — одна запись и ФИО совпадает; «неоднозначно» — несколько записей или
  ФИО не совпадает; «не найдено» — записи нет. Сопоставления по email нет (Q-20).
* Решения по неоднозначным (``/resolve``) — суперадминистратор подтверждает кандидата или
  отклоняет (``object_guid = null``), по одному (C-13). Решения хранятся до применения (сутки).
* Применение (``dry_run = false``, step-up) — только когда решены все неоднозначные (иначе 409
  ``MODE_SWITCH_UNRESOLVED``) и параметры AD сохранены после обеих проверок
  (``AD_CHECKS_REQUIRED``): сопоставленные получают ``ad_object_guid`` и ``source = ad``, локальные
  пароли, история паролей и ссылки установки и сброса удаляются, TOTP сохраняется; несопоставленные
  и отклонённые блокируются с причиной ``not_matched``; все сессии, кроме сессии того, кто
  переключает, завершаются; ``auth.mode = ad``.
* Каждый отчёт и применение — ``system.auth_mode.switched`` (с ``dry_run``); применение оповещает
  ИБ и администраторов (SEC-011). ``mode = local`` или повторный переход — 409
  ``MODE_SWITCH_NOT_ALLOWED``: обратно — только ``estimator auth-mode local`` (AUTH-019).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.providers import ldap
from estimator.auth.providers.ldap import AdConfigError, AdUnavailableError, Entry
from estimator.auth.sessions import RevokeReason, SessionService
from estimator.db.enums import SystemRole, UserBlockReason, UserSource, UserStatus
from estimator.db.models.settings import SystemSetting
from estimator.db.models.users import AuthToken, PasswordHistory, User, UserRole, UserSession
from estimator.logging import get_logger
from estimator.security import audit
from estimator.services.common import user_ref

log = get_logger(__name__)

DECISIONS_KEY = "auth:switch:decisions"
LAST_KEY = "auth:switch:last"
DECISIONS_TTL = 24 * 3600
REJECT = "reject"


def _name(value: str) -> str:
    return " ".join(value.replace("ё", "е").replace("Ё", "Е").split()).casefold()


@dataclass
class Candidate:
    user: User
    entries: list[Entry] = field(default_factory=list)

    def out(self) -> dict[str, Any]:
        return {"user_id": str(self.user.id), "login": self.user.login,
                "full_name": self.user.full_name,
                "ad_candidates": [{"object_guid": str(e.object_guid), "login": e.login,
                                   "full_name": e.full_name} for e in self.entries]}  # fmt: skip


@dataclass
class Report:
    matched: list[Candidate] = field(default_factory=list)
    ambiguous: list[Candidate] = field(default_factory=list)
    not_found: list[Candidate] = field(default_factory=list)
    confirmed: int = 0
    rejected: int = 0

    def out(self, applied: bool) -> dict[str, Any]:
        return {"matched": [c.out() for c in self.matched],
                "ambiguous": [c.out() for c in self.ambiguous],
                "not_found": [c.out() for c in self.not_found], "applied": applied}  # fmt: skip


async def _local_users(db: AsyncSession) -> list[User]:
    superadmin = exists().where(UserRole.user_id == User.id, UserRole.role == SystemRole.SUPERADMIN)
    return list((await db.scalars(
        select(User).where(User.source == UserSource.LOCAL, User.status != UserStatus.ANONYMIZED,
                           ~superadmin).order_by(User.login)
    )).all())  # fmt: skip


async def _decisions(redis: Redis) -> dict[str, str]:
    raw = await redis.hgetall(DECISIONS_KEY)
    return {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()}  # fmt: skip


async def _ensure_ready(db: AsyncSession) -> ldap.AdConfig:
    from estimator.auth import ad_settings
    from estimator.auth.policy import load_auth_mode

    if await load_auth_mode(db) == "ad":
        raise ApiError("MODE_SWITCH_NOT_ALLOWED", detail="Вход уже идёт через Active Directory")
    values, password = await ldap.stored_values(db)
    ver = await ad_settings.verification(db)
    same = ver.get("params_sha256") == ldap.fingerprint(values, password)
    missing = [n for n in ("connection", "login") if not same or not ver.get(f"{n}_ok_at")]
    if missing:
        raise ApiError("AD_CHECKS_REQUIRED", missing=missing,
                       detail="Сначала сохраните параметры AD после проверок")  # fmt: skip
    try:
        config = ldap.AdConfig.from_values(values, password)
    except AdConfigError:
        raise ApiError("AD_CHECKS_REQUIRED", missing=["connection", "login"]) from None
    if not config.access_groups:
        raise ApiError("AD_CHECKS_REQUIRED", missing=["login"],
                       detail="Укажите хотя бы одну группу доступа")  # fmt: skip
    return config


async def build_report(db: AsyncSession, redis: Redis, config: ldap.AdConfig) -> Report:
    directory = ldap.directory(config)
    decisions = await _decisions(redis)
    report = Report()
    try:
        for user in await _local_users(db):
            entries = await directory.find_user(user.login)
            item = Candidate(user, entries)
            choice = decisions.get(str(user.id))
            if not entries:
                report.not_found.append(item)
            elif len(entries) == 1 and _name(entries[0].full_name) == _name(user.full_name):
                report.matched.append(item)
            elif choice == REJECT:
                report.rejected += 1
                report.not_found.append(item)
            elif choice and (chosen := [e for e in entries if str(e.object_guid) == choice]):
                report.confirmed += 1
                report.matched.append(Candidate(user, chosen))
            else:
                report.ambiguous.append(item)
    except AdUnavailableError:
        raise ApiError("AUTH_SERVICE_UNAVAILABLE") from None
    return report


async def _audit(db: AsyncSession, actor: Principal, report: Report, *, dry_run: bool,
                 ip: str | None) -> None:  # fmt: skip
    await audit.write(
        db, "system.auth_mode.switched", user_id=actor.user_id, login=actor.login, ip=ip,
        session_id=actor.session_id, object_type="setting", object_id="auth.mode",
        details={"from": "local", "to": "ad", "via": "ui", "matched": len(report.matched),
                 "ambiguous_confirmed": report.confirmed, "ambiguous_rejected": report.rejected,
                 "not_found_blocked": len(report.not_found), "dry_run": dry_run},
    )  # fmt: skip


async def switch(db: AsyncSession, redis: Redis, actor: Principal, mode: str, *, dry_run: bool,
                 ip: str | None = None) -> dict[str, Any]:  # fmt: skip
    if mode != "ad":
        raise ApiError("MODE_SWITCH_NOT_ALLOWED")
    config = await _ensure_ready(db)
    report = await build_report(db, redis, config)
    if dry_run:
        await _audit(db, actor, report, dry_run=True, ip=ip)
        return report.out(applied=False)
    if report.ambiguous:
        raise ApiError("MODE_SWITCH_UNRESOLVED", unresolved=len(report.ambiguous),
                       detail=f"Решите по каждому неоднозначному совпадению: осталось "
                              f"{len(report.ambiguous)}")  # fmt: skip
    await _apply(db, redis, actor, report)
    await _audit(db, actor, report, dry_run=False, ip=ip)
    out = report.out(applied=True)
    last = {"at": dt.datetime.now(dt.UTC).isoformat(), "by": str(actor.user_id),
            "resolved": report.confirmed + report.rejected, "report": out}  # fmt: skip
    from estimator.db.session import after_commit

    async def remember() -> None:
        await redis.set(LAST_KEY, json.dumps(last, ensure_ascii=False))
        await redis.delete(DECISIONS_KEY)

    after_commit(db, remember)
    return out


async def _apply(db: AsyncSession, redis: Redis, actor: Principal, report: Report) -> None:
    for item in report.matched:
        user, entry = item.user, item.entries[0]
        user.source = UserSource.AD
        user.ad_object_guid = entry.object_guid
        user.password_hash = None
        user.password_changed_at = None
        if user.status is UserStatus.PENDING_PASSWORD:
            user.status = UserStatus.ACTIVE
        await db.execute(delete(PasswordHistory).where(PasswordHistory.user_id == user.id))
        await db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    for item in report.not_found:
        user = item.user
        if user.status is not UserStatus.BLOCKED:
            user.status = UserStatus.BLOCKED
            user.block_reason = UserBlockReason.NOT_MATCHED
            user.blocked_at = dt.datetime.now(dt.UTC)
    await db.flush()
    await db.merge(SystemSetting(key="auth.mode", value="ad", updated_by=actor.user_id))
    await db.flush()
    await end_sessions(db, SessionService(redis), keep=actor.session_id)


async def end_sessions(db: AsyncSession, sessions: SessionService, *, keep: str | None) -> int:
    """Завершить все сессии всех пользователей, кроме ``keep`` (сессии того, кто переключает)."""
    users = (await db.scalars(
        select(UserSession.user_id).where(UserSession.revoked_at.is_(None)).distinct()
    )).all()  # fmt: skip
    ended = 0
    for user_id in users:
        ended += await sessions.revoke_user(db, user_id, RevokeReason.MODE_SWITCH,
                                            except_session_id=keep)  # fmt: skip
    return ended


Decision = tuple[uuid.UUID, uuid.UUID | None]


def _invalid(message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": "/decisions", "code": "invalid", "message": message}],
    )


async def resolve(db: AsyncSession, redis: Redis, actor: Principal,
                  decisions: Sequence[Decision]) -> dict[str, Any]:  # fmt: skip
    config = await _ensure_ready(db)
    before = await build_report(db, redis, config)
    open_ = {c.user.id: c for c in before.ambiguous}
    for user_id, guid in decisions:
        item = open_.get(user_id)
        if item is None:
            raise _invalid("Этого пользователя нет среди неоднозначных")
        if guid is not None and guid not in {e.object_guid for e in item.entries}:
            raise _invalid("Кандидат не из списка AD")
    for user_id, guid in decisions:
        await redis.hset(DECISIONS_KEY, str(user_id), str(guid) if guid else REJECT)
    await redis.expire(DECISIONS_KEY, DECISIONS_TTL)
    return (await build_report(db, redis, config)).out(applied=False)


async def last(db: AsyncSession, redis: Redis) -> dict[str, Any] | None:
    raw = await redis.get(LAST_KEY)
    if not raw:
        return None
    data = json.loads(raw)
    by = await db.get(User, uuid.UUID(data["by"]))
    return {"at": data["at"], "by": user_ref(by.id, by.full_name) if by else
            user_ref(uuid.UUID(data["by"]), "—"), "resolved": data["resolved"],
            "report": data["report"]}  # fmt: skip
