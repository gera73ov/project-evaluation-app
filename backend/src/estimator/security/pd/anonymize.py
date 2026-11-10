"""Анонимизация пользователя (SEC-014; SEC-PD-01, SEC-PD-03, Q-34).

Только суперадминистратор, со step-up, только заблокированная учётка (409 ``USER_NOT_BLOCKED``):

* ФИО → «Удалённый пользователь #<номер>» (номер из ``users_anonymized_no_seq``);
* логин и email → случайные значения (почта в зоне ``.invalid``: письмо на неё не уйдёт);
* сессии завершаются и удаляются вместе с IP и user-agent; TOTP, резервные коды, история паролей,
  известные устройства, ссылки активации и системные роли удаляются;
* связь с AD (``ad_object_guid``) снимается — новый вход того же человека через AD создаёт новую
  учётку (FR-AUTH-AD-06);
* строка ``users`` остаётся: авторство в проектах, обсуждениях и истории ссылается на неё и
  показывается обезличенно. Журнал аудита (в том числе IP и прежний логин в старых записях) не
  трогается до истечения срока хранения (SEC-AUD-04).

Событие ``users.anonymized`` с ``{anonymous_no}`` пишется в той же транзакции.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.sessions.service import RevokeReason, SessionService
from estimator.db.enums import SystemRole, UserStatus
from estimator.db.models.users import (
    ANONYMIZED_NO_SEQ,
    AuthToken,
    BackupCode,
    KnownDevice,
    PasswordHistory,
    User,
    UserRole,
    UserSession,
)
from estimator.security import audit
from estimator.security.authz import role_rules

NAME_TEMPLATE = "Удалённый пользователь #{}"
EMAIL_DOMAIN = "anonymized.invalid"  # RFC 2606: зона .invalid не резолвится
LISTED = (UserStatus.BLOCKED, UserStatus.ANONYMIZED)

#: Персональные данные в связанных таблицах: удаляются целиком
_PERSONAL = (BackupCode, PasswordHistory, KnownDevice, AuthToken, UserRole)


def random_login() -> str:
    return f"deleted-{secrets.token_hex(12)}"


def random_email() -> str:
    return f"{secrets.token_hex(12)}@{EMAIL_DOMAIN}"


async def anonymize(
    db: AsyncSession, sessions: SessionService, actor: Principal, user_id: uuid.UUID
) -> int:
    """Обезличить заблокированного пользователя; вернуть его номер «Удалённый пользователь #N»."""
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ApiError("NOT_FOUND")
    if user.status != UserStatus.BLOCKED:
        raise ApiError("USER_NOT_BLOCKED")
    await role_rules.ensure_not_last_superadmin(db, user.id)

    await sessions.revoke_user(db, user.id, RevokeReason.BLOCKED)
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    for model in _PERSONAL:
        await db.execute(delete(model).where(model.user_id == user.id))

    number = int(await db.scalar(select(ANONYMIZED_NO_SEQ.next_value())))
    user.full_name = NAME_TEMPLATE.format(number)
    user.login = random_login()
    user.email = random_email()
    user.timezone = None
    user.ad_object_guid = None
    user.password_hash = None
    user.password_changed_at = None
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.status = UserStatus.ANONYMIZED
    user.block_reason = None
    user.anonymized_no = number
    user.updated_by = actor.user_id
    await db.flush()

    await audit.write(
        db, "users.anonymized", user_id=actor.user_id, login=actor.login,
        session_id=actor.session_id, object_type="user", object_id=user.id,
        details={"anonymous_no": number},
    )  # fmt: skip
    return number


@dataclass(frozen=True)
class ListFilter:
    status: UserStatus = UserStatus.BLOCKED
    q: str | None = None


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _iso(value: Any) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


async def list_users(
    db: AsyncSession, filt: ListFilter, *, after: dict[str, Any] | None, limit: int
) -> list[dict[str, Any]]:
    """Заблокированные или анонимизированные учётки для экрана «Анонимизация» (CR-010).

    Порядок — ``blocked_at`` по убыванию (без даты — в конце), затем ``id``. Возвращает до
    ``limit + 1`` строк: лишняя значит «есть следующая страница». Почта не отдаётся.
    """
    sort_key = func.coalesce(User.blocked_at, func.to_timestamp(0))
    stmt = select(User, sort_key.label("k")).where(User.status == filt.status)
    if filt.q and filt.q.strip():
        pattern = _like(filt.q.strip())
        stmt = stmt.where(
            or_(User.login.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\"))
        )
    if after is not None:
        try:
            key = dt.datetime.fromisoformat(str(after["k"]))
            last = uuid.UUID(str(after["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("CURSOR_INVALID") from exc
        if key.tzinfo is None:
            raise ApiError("CURSOR_INVALID")
        stmt = stmt.where(or_(sort_key < key, (sort_key == key) & (User.id > last)))
    rows = (await db.execute(stmt.order_by(sort_key.desc(), User.id).limit(limit + 1))).all()
    roles = await _roles(db, [r[0].id for r in rows])
    return [
        {
            "id": u.id,
            "login": u.login,
            "full_name": u.full_name,
            "roles": sorted(roles.get(u.id, ())),
            "status": u.status.value,
            "blocked_at": _iso(u.blocked_at),
            "last_login_at": _iso(u.last_login_at),
            "_k": k.isoformat(),
        }
        for u, k in rows
    ]


async def _roles(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, set[SystemRole]]:
    out: dict[uuid.UUID, set[SystemRole]] = {}
    if not ids:
        return out
    for uid, role in await db.execute(
        select(UserRole.user_id, UserRole.role).where(UserRole.user_id.in_(ids))
    ):
        out.setdefault(uid, set()).add(role)
    return out
