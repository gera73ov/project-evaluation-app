"""Условия оповещений ИБ (SEC-011; SEC-AUTH-07, contracts/audit-events.yaml ``alert`` и
``security_alerts``).

* :func:`triggered` — сработало ли условие ``alert: when …`` события по его ``details``.
  :func:`estimator.security.audit.write` вызывает её сама, поэтому вызывающему коду не нужно
  помнить условия (``alert=True`` по-прежнему принудительно включает оповещение);
* :func:`alert_key` — ключ оповещения из ``security_alerts`` (подпись письма) по событию.

Модуль не зависит от записи аудита, чтобы ``security.audit`` мог его импортировать.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PRIVILEGED = frozenset({"admin", "superadmin"})
ROLE_ALERT = PRIVILEGED | {"security_auditor"}
SETTINGS_ALERT_SECTIONS = {
    "smtp": "smtp_changed",
    "security.admin_networks": "admin_networks_changed",
    "security.mfa_policy": "mfa_requirement_disabled",
}
#: Событие с единственным ключом оповещения
_SIMPLE = {
    "system.auth_mode.switched": "auth_mode_switched",
    "system.ad_settings.changed": "ad_settings_changed",
    "system.privileged_account.changed": "privileged_account_changed",
    "auth.password.reset_issued": "privileged_password_reset",
    "auth.mfa.reset": "privileged_totp_reset",
    "security.superadmin_login_failures": "superadmin_login_failures",
    "security.login_failures_burst": "login_failures_burst",
    "system.audit_chain.verified": "audit_chain_broken",
}


def _roles(details: Mapping[str, Any], *keys: str) -> set[str]:
    out: set[str] = set()
    for key in keys:
        out |= {str(r) for r in details.get(key) or ()}
    return out


def _required_turned_off(changes: Any) -> bool:
    """В ``changes`` (ключ → [было, стало]) обязательный TOTP стал необязательным хоть для одной
    роли. Пара может быть и целым значением раздела ``{роль: optional|required}``."""
    if isinstance(changes, Mapping):
        return any(_required_turned_off(v) for v in changes.values())
    if isinstance(changes, list | tuple) and len(changes) == 2:
        old, new = changes
        if isinstance(old, Mapping):
            new_map = new if isinstance(new, Mapping) else {}
            return any(v == "required" and new_map.get(k) != "required" for k, v in old.items())
        return old == "required" and new != "required"
    return False


def triggered(event_type: str, details: Mapping[str, Any]) -> bool:
    """Условие ``alert: when …`` из контракта для ``details`` события."""
    if event_type == "auth.password.reset_issued":
        return bool(_roles(details, "target_roles") & PRIVILEGED)
    if event_type == "users.roles.changed":
        return bool(_roles(details, "added", "removed") & ROLE_ALERT)
    if event_type == "system.settings.changed":
        section = details.get("section")
        if section == "security.mfa_policy":
            return _required_turned_off(details.get("changes"))
        return section in SETTINGS_ALERT_SECTIONS
    if event_type == "system.auth_mode.switched":
        return not details.get("dry_run", False)
    if event_type == "system.audit_chain.verified":
        return details.get("ok") is False
    return False


def alert_key(event_type: str, details: Mapping[str, Any]) -> str:
    """Ключ ``security_alerts`` для письма; для неизвестного события — его тип."""
    if event_type == "system.settings.changed":
        return SETTINGS_ALERT_SECTIONS.get(str(details.get("section")), event_type)
    if event_type == "users.roles.changed":
        if "security_auditor" in _roles(details, "added", "removed"):
            return "security_auditor_role"
        return "privileged_account_changed"
    return _SIMPLE.get(event_type, event_type)
