"""Политика второго фактора и гейты сессии (AUTH-007).

SPEC FR-SA-04, FR-2FA-02, FR-2FA-04, FR-2FA-05, R-05.


* ``security.mfa_policy`` — «required/optional» по системной роли; ``user`` — пользователь без
  системных ролей. Обязателен, если обязателен хотя бы для одной роли; для суперадминистратора —
  всегда. Политика читается при входе: изменение действует со следующего входа (FR-2FA-04).
* Зависимости FastAPI:

  - :data:`ActivePrincipal` — сессия после подключения TOTP (иначе 403 ``TOTP_ENROLL_REQUIRED``),
    приложение настроено (иначе 503 ``APP_SETUP_IN_PROGRESS``), CSRF для изменяющих запросов;
  - :data:`PreMfaPrincipal` — допускает сессию принудительного подключения (enroll, logout),
    тоже с проверкой CSRF;
  - :func:`require_totp` — денежные и заметочные эндпоинты (403 ``TOTP_REQUIRED``, R-05);
  - :func:`require_step_up` — действия SEC-AUTH-05 (403 ``STEP_UP_REQUIRED``).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from estimator.auth.context import Principal, current_principal
from estimator.auth.policy import read_settings
from estimator.auth.setup_gate import ensure_setup_allows
from estimator.db.enums import SystemRole
from estimator.db.session import DbSession
from estimator.security.web.csrf import check_csrf

#: Ключ ``user`` — пользователь без системных ролей (contracts/settings.schema.json).
PLAIN_USER = "user"
DEFAULTS: dict[str, str] = {
    "admin": "required",
    "moderator": "required",
    "presale": "required",
    "presale_head": "required",
    "security_auditor": "required",
    PLAIN_USER: "optional",
}


@dataclass(frozen=True)
class MfaPolicy:
    by_role: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULTS))

    @classmethod
    def from_setting(cls, value: Mapping[str, Any] | None) -> MfaPolicy:
        return cls({**DEFAULTS, **(value or {})})

    def required_for(self, roles: Collection[SystemRole | str]) -> bool:
        names = {str(SystemRole(r)) for r in roles}
        if SystemRole.SUPERADMIN.value in names:
            return True
        if not names:
            return self.by_role.get(PLAIN_USER) == "required"
        return any(self.by_role.get(name) == "required" for name in names)


async def load_mfa_policy(conn: AsyncConnection | AsyncSession) -> MfaPolicy:
    values = await read_settings(conn, "security.mfa_policy")
    return MfaPolicy.from_setting(values.get("security.mfa_policy"))


class ForbiddenError(HTTPException):
    """403 с кодом из contracts/errors.yaml."""

    def __init__(self, code: str) -> None:
        super().__init__(status_code=403, detail={"code": code})


async def active_principal(
    request: Request, principal: Annotated[Principal, Depends(current_principal)], db: DbSession
) -> Principal:
    """Порядок проверок — contracts/api-conventions.md 4.2: настройка, сессия, TOTP, CSRF."""
    await ensure_setup_allows(db, superadmin=principal.is_superadmin)
    if principal.enrollment_required:
        raise ForbiddenError("TOTP_ENROLL_REQUIRED")
    check_csrf(request, principal.session.csrf)
    return principal


def pre_mfa_principal(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Principal:
    check_csrf(request, principal.session.csrf)
    return principal


#: Обычные эндпоинты: сессия без незавершённого принудительного подключения TOTP.
ActivePrincipal = Annotated[Principal, Depends(active_principal)]
#: ``session.pre_mfa``: подключение TOTP и выход.
PreMfaPrincipal = Annotated[Principal, Depends(pre_mfa_principal)]


def require_totp(principal: ActivePrincipal) -> Principal:
    """Деньги и закрытые заметки — только после TOTP в текущей сессии (FR-2FA-05)."""
    if not principal.mfa_passed:
        raise ForbiddenError("TOTP_REQUIRED")
    return principal


def require_step_up(principal: ActivePrincipal) -> Principal:
    """Действия с повторным подтверждением (SEC-AUTH-05): step-up не старше 5 минут."""
    if not principal.step_up_active():
        raise ForbiddenError("STEP_UP_REQUIRED")
    return principal


TotpPrincipal = Annotated[Principal, Depends(require_totp)]
StepUpPrincipal = Annotated[Principal, Depends(require_step_up)]
