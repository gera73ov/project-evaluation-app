"""Политика паролей режима «Приложение» (AUTH-008; FR-AUTH-LOC-02, Q-24).

Значения — ``security.password_policy`` (по умолчанию NIST SP 800-63B: 12–128 символов, без
требований к составу и срока действия). Проверки возвращают коды нарушений из расширения
``violations`` ошибки ``PASSWORD_POLICY_VIOLATION``: ``too_short``, ``too_long``, ``common``,
``matches_personal``, ``reused``, ``composition``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

from estimator.auth.providers.local import verify_password

#: Части ФИО, логина и email короче этого не считаются совпадением (слишком много ложных).
MIN_PERSONAL_PART = 3


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    """100 000 распространённых паролей (``auth/data/common-passwords.txt``), в нижнем регистре."""
    text = (
        resources.files("estimator.auth").joinpath("data/common-passwords.txt").read_text("utf-8")
    )
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int = 12
    max_length: int = 128
    check_common_passwords: bool = True
    forbid_personal_data: bool = True
    history: int = 5
    expiry_days: int | None = None
    require_uppercase: bool = False
    require_digit: bool = False
    require_special: bool = False

    @classmethod
    def from_setting(cls, value: Mapping[str, Any] | None) -> PasswordPolicy:
        base = cls()
        v = value or {}
        expiry = v.get("expiry_days", base.expiry_days)
        return cls(
            min_length=int(v.get("min_length", base.min_length)),
            max_length=int(v.get("max_length", base.max_length)),
            check_common_passwords=bool(v.get("check_common_passwords", True)),
            forbid_personal_data=bool(v.get("forbid_personal_data", True)),
            history=int(v.get("history", base.history)),
            expiry_days=int(expiry) if expiry is not None else None,
            require_uppercase=bool(v.get("require_uppercase", False)),
            require_digit=bool(v.get("require_digit", False)),
            require_special=bool(v.get("require_special", False)),
        )

    def is_expired(self, changed_at: datetime | None, now: datetime | None = None) -> bool:
        """Пароль старше ``expiry_days`` (``None`` — срок не ограничен)."""
        if self.expiry_days is None or changed_at is None:
            return False
        return (now or datetime.now(UTC)) - changed_at > timedelta(days=self.expiry_days)

    def violations(
        self,
        password: str,
        *,
        login: str = "",
        full_name: str = "",
        email: str | None = None,
        previous_hashes: Iterable[str] = (),
    ) -> list[str]:
        """Коды нарушений по порядку проверок; пустой список — пароль подходит."""
        found: list[str] = []
        length = len(password)
        if length < self.min_length:
            found.append("too_short")
        if length > self.max_length:
            found.append("too_long")
        if self.check_common_passwords and _normalize(password) in common_passwords():
            found.append("common")
        if self.forbid_personal_data and _matches_personal(password, login, full_name, email):
            found.append("matches_personal")
        if not self._composition_ok(password):
            found.append("composition")
        if "too_long" not in found and any(verify_password(h, password) for h in previous_hashes):
            found.append("reused")
        return found

    def _composition_ok(self, password: str) -> bool:
        if self.require_uppercase and not any(c.isupper() for c in password):
            return False
        if self.require_digit and not any(c.isdigit() for c in password):
            return False
        return not (self.require_special and all(c.isalnum() or c.isspace() for c in password))


def _personal_parts(login: str, full_name: str, email: str | None) -> set[str]:
    parts = {_normalize(login)}
    if email:
        address = _normalize(email)
        parts |= {address, address.partition("@")[0]}
    name = _normalize(full_name)
    parts.add(re.sub(r"\s+", "", name))
    parts |= set(re.split(r"[\s.\-_]+", name))
    parts |= set(re.split(r"[.\-_]+", _normalize(login)))
    return {p for p in parts if len(p) >= MIN_PERSONAL_PART}


def _matches_personal(password: str, login: str, full_name: str, email: str | None) -> bool:
    """Пароль совпадает с логином, ФИО или email либо содержит их части (без учёта регистра)."""
    candidate = _normalize(password)
    return any(part in candidate for part in _personal_parts(login, full_name, email))
