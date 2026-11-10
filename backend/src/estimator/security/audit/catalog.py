"""Каталог событий аудита — копия contracts/audit-events.yaml для рантайма (SEC-004).

Контракты в образ не попадают, поэтому каталог продублирован здесь; совпадение с контрактом
проверяет ``tests/unit/sec/test_audit_catalog.py``. Меняется вместе с контрактом (CR).
"""

from __future__ import annotations

from dataclasses import dataclass

CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class EventSpec:
    category: str
    object_type: str | None
    details: frozenset[str]
    #: Оповещение ИБ (SEC-AUTH-07): None, "always" или "conditional" — условие из контракта
    #: проверяет :func:`estimator.security.alerts.rules.triggered` при записи события.
    alert: str | None = None


EVENTS: dict[str, EventSpec] = {
    "auth.login.succeeded": EventSpec(
        "auth", "session", frozenset(["method", "mfa", "new_device"]), None
    ),
    "auth.login.failed": EventSpec("auth", "user", frozenset(["method", "reason", "step"]), None),
    "auth.logout": EventSpec("auth", "session", frozenset([]), None),
    "auth.session.expired": EventSpec("auth", "session", frozenset(["reason"]), None),
    "auth.sessions.terminated": EventSpec("auth", "user", frozenset(["count", "reason"]), None),
    "auth.sessions.revoked_by_ad": EventSpec(
        "auth", "user", frozenset(["block_reason", "sessions"]), None
    ),
    "auth.lockout.pair_locked": EventSpec("auth", "user", frozenset(["failures", "minutes"]), None),
    "auth.lockout.superadmin_delay": EventSpec(
        "auth", "user", frozenset(["consecutive_failures", "delay_seconds"]), None
    ),
    "auth.step_up.passed": EventSpec("auth", "session", frozenset(["purpose"]), None),
    "auth.step_up.failed": EventSpec("auth", "session", frozenset(["purpose", "reason"]), None),
    "auth.password.reset_requested": EventSpec("auth", "user", frozenset(["email_sent"]), None),
    "auth.password.set": EventSpec("auth", "user", frozenset(["via"]), None),
    "auth.password.changed": EventSpec("auth", "user", frozenset([]), None),
    "auth.password.reset_issued": EventSpec(
        "auth",
        "user",
        frozenset(["delivery", "target_roles"]),
        "conditional",
    ),
    "auth.mfa.enrolled": EventSpec("auth", "user", frozenset(["forced"]), None),
    "auth.mfa.disabled": EventSpec("auth", "user", frozenset([]), None),
    "auth.mfa.reset": EventSpec("auth", "user", frozenset(["target_roles"]), "always"),
    "auth.mfa.backup_codes_regenerated": EventSpec("auth", "user", frozenset([]), None),
    "users.created": EventSpec(
        "users_roles", "user", frozenset(["project_id", "roles", "source"]), None
    ),
    "users.updated": EventSpec("users_roles", "user", frozenset(["changes"]), None),
    "users.blocked": EventSpec("users_roles", "user", frozenset(["block_reason"]), None),
    "users.unblocked": EventSpec(
        "users_roles", "user", frozenset(["automatic", "previous_reason"]), None
    ),
    "users.anonymized": EventSpec("users_roles", "user", frozenset(["anonymous_no"]), None),
    "users.roles.changed": EventSpec(
        "users_roles",
        "user",
        frozenset(["added", "removed", "source"]),
        "conditional",
    ),
    "users.ad_sync.completed": EventSpec(
        "users_roles",
        None,
        frozenset(
            ["blocked", "checked", "kind", "roles_changed", "skipped_ad_unavailable", "unblocked"]
        ),
        None,
    ),
    "users.ad_role_mapping.report": EventSpec(
        "users_roles", None, frozenset(["applied", "roles_to_remove"]), None
    ),
    "users.replaced_everywhere": EventSpec(
        "users_roles",
        "user",
        frozenset(
            ["projects_applied", "projects_skipped", "questions_redirected", "replacement_user_id"]
        ),
        None,
    ),
    "system.setup.step_completed": EventSpec("system", "setting", frozenset(["step"]), None),
    "system.setup.finished": EventSpec("system", None, frozenset([]), None),
    "system.auth_mode.switched": EventSpec(
        "system",
        "setting",
        frozenset(
            [
                "ambiguous_confirmed",
                "ambiguous_rejected",
                "dry_run",
                "from",
                "matched",
                "not_found_blocked",
                "to",
                "via",
            ]
        ),
        "conditional",
    ),
    "system.ad_settings.changed": EventSpec("system", "setting", frozenset(["changes"]), "always"),
    "system.settings.changed": EventSpec(
        "system",
        "setting",
        frozenset(["changes", "section"]),
        "conditional",
    ),
    "system.privileged_account.changed": EventSpec(
        "system", "user", frozenset(["op", "role"]), "always"
    ),
    "system.cli.executed": EventSpec(
        "system",
        "cli_command",
        frozenset(["args", "command", "exit_code", "host", "os_user"]),
        None,
    ),
    "system.audit_chain.verified": EventSpec(
        "system", "audit_log", frozenset(["checked", "first_broken_id", "ok"]), "conditional"
    ),
    "system.audit.purged": EventSpec(
        "system", "audit_log", frozenset(["anchor_hash", "before", "deleted"]), None
    ),
    "system.alert.delivery_failed": EventSpec(
        "system", "setting", frozenset(["alert_type", "channel"]), None
    ),
    "dict.changed": EventSpec(
        "dictionaries", "dictionary_item", frozenset(["changes", "dictionary", "op"]), None
    ),
    "dict.proposed_type.decided": EventSpec(
        "dictionaries",
        "dictionary_item",
        frozenset(["decision", "merged_into", "nodes_relinked", "project_id"]),
        None,
    ),
    "project.created": EventSpec(
        "projects", "project", frozenset(["copied_from", "rates_copied"]), None
    ),
    "project.status.changed": EventSpec(
        "projects", "project", frozenset(["automatic", "cancel_reason", "from", "to"]), None
    ),
    "project.team.changed": EventSpec(
        "projects",
        "project_member",
        frozenset(
            [
                "added_by_admin_self",
                "discipline_id",
                "is_reviewer",
                "member_user_id",
                "op",
                "role",
                "via",
            ]
        ),
        None,
    ),
    "project.moderator.transferred": EventSpec(
        "projects", "project", frozenset(["added_user_id", "removed_user_id"]), None
    ),
    "project.questions.redirected": EventSpec(
        "projects", "project", frozenset(["from_user_id", "threads", "to_user_id"]), None
    ),
    "project.opened_by_presale_head": EventSpec("projects", "project", frozenset([]), None),
    "project.joined_as_moderator": EventSpec("projects", "project", frozenset([]), None),
    "project.support_session.opened": EventSpec(
        "projects", "support_session", frozenset(["expires_at", "reason"]), None
    ),
    "project.money.changed": EventSpec(
        "projects", "project", frozenset(["discipline_ids", "fields"]), None
    ),
    "project.snapshot.created": EventSpec(
        "projects", "snapshot", frozenset(["payload_sha256"]), None
    ),
    "project.snapshot.invalidated": EventSpec("projects", "snapshot", frozenset([]), None),
    "export.created": EventSpec(
        "projects", "export", frozenset(["kind", "rows", "snapshot_id", "with_money"]), None
    ),
    "export.downloaded": EventSpec("projects", "export", frozenset(["kind"]), None),
    "project.document.changed": EventSpec(
        "projects", "document", frozenset(["mime", "op", "scan_status", "size_bytes"]), None
    ),
    "project.purged": EventSpec(
        "projects",
        "project",
        frozenset(["approved_by_login", "composition", "dry_run", "project_name", "ticket"]),
        None,
    ),
    "security.access_denied": EventSpec(
        "security", None, frozenset(["method", "permission", "route", "status", "suppressed"]), None
    ),
    "security.network_denied": EventSpec("security", None, frozenset(["route"]), None),
    "security.rate_limited": EventSpec("security", None, frozenset(["limit", "retry_after"]), None),
    "security.file_infected": EventSpec(
        "security", "document", frozenset(["mime", "scan_status", "signature", "size_bytes"]), None
    ),
    "security.superadmin_login_failures": EventSpec(
        "security", "user", frozenset(["consecutive_failures"]), "always"
    ),
    "security.login_failures_burst": EventSpec(
        "security", "user", frozenset(["distinct_ips", "failures_hour"]), "always"
    ),
    "audit.viewed": EventSpec("audit", "audit_log", frozenset(["filters"]), None),
    "audit.exported": EventSpec("audit", "audit_log", frozenset(["filters", "rows"]), None),
}

COMMON_DETAILS = frozenset(["actor", "os_user", "project_id"])
FORBIDDEN_DETAIL_KEYS = frozenset(
    [
        "amount",
        "authorization",
        "backup_code",
        "bind_password",
        "body",
        "code",
        "comment",
        "comment_lines",
        "contract_amount",
        "cookie",
        "cost",
        "cost_rub",
        "exchange_rate",
        "file_name",
        "key",
        "money",
        "o",
        "p",
        "password",
        "password_hash",
        "private_key",
        "quote_cur",
        "quote_rub",
        "r",
        "rate",
        "rate_rub",
        "secret",
        "smtp_password",
        "text",
        "title",
        "token",
        "totp",
        "vat_percent",
    ]
)
OBJECT_TYPES = frozenset(
    [
        "audit_log",
        "cli_command",
        "dictionary_item",
        "document",
        "export",
        "node",
        "project",
        "project_member",
        "session",
        "setting",
        "snapshot",
        "support_session",
        "thread",
        "user",
    ]
)
ACTORS = frozenset(["anonymous", "cli", "system", "user"])
LOGIN_FAILURE_REASONS = frozenset(
    [
        "ad_account_disabled",
        "ad_ambiguous",
        "ad_not_in_group",
        "ad_unavailable",
        "empty_credentials",
        "invalid_backup_code",
        "invalid_totp",
        "locked_out",
        "pending_password",
        "rate_limited",
        "setup_in_progress",
        "user_blocked",
        "user_not_found",
        "wrong_password",
    ]
)
SECURITY_ALERTS: dict[str, str] = {
    "smtp_changed": "system.settings.changed",
    "auth_mode_switched": "system.auth_mode.switched",
    "ad_settings_changed": "system.ad_settings.changed",
    "privileged_account_changed": "system.privileged_account.changed",
    "privileged_password_reset": "auth.password.reset_issued",  # nosec B105 — тип события, не пароль
    "privileged_totp_reset": "auth.mfa.reset",
    "security_auditor_role": "users.roles.changed",
    "mfa_requirement_disabled": "system.settings.changed",
    "admin_networks_changed": "system.settings.changed",
    "superadmin_login_failures": "security.superadmin_login_failures",
    "login_failures_burst": "security.login_failures_burst",
    "audit_chain_broken": "system.audit_chain.verified",
}
