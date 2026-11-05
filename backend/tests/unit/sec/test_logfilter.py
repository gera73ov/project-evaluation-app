"""SEC-009: пароли, токены, коды и cookie не попадают в логи (SEC-AUTH-04, CL-11)."""

from __future__ import annotations

import json
import logging

import pytest

from estimator.logging import configure_logging, get_logger
from estimator.security.logfilter import (
    REDACTED,
    AccessLogQueryFilter,
    is_secret_key,
    redact,
    redact_text,
)

pytestmark = [pytest.mark.spec("SEC-AUTH-04"), pytest.mark.spec("CL-11")]

PASSWORD = "Tr0ub4dor&3-very-secret"
TOKEN = "Zk3q9V0pQd1sXz7yW2rT4uI6oP8aS0dF"
SESSION = "s3ss10n-1d-0123456789abcdef"
TOTP = "492039"


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "Password",
        "smtp_password",
        "token",
        "csrf_token",
        "X-CSRF-Token",
        "cookie",
        "set-cookie",
        b"cookie",
        "authorization",
        "secret",
        "totp_secret_enc",
        "code",
        "otp",
        "backup_code",
        "encryption_key",
        "session",
    ],
)
def test_secret_keys(key: object) -> None:
    assert is_secret_key(key)


@pytest.mark.parametrize("key", ["status_code", "error_code", "exit_code", "login", "user_id"])
def test_not_secret_keys(key: str) -> None:
    assert not is_secret_key(key)


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        (f"POST /api/v1/auth/activate?token={TOKEN}&x=1", TOKEN),
        (f"password={PASSWORD}&login=ivanov", PASSWORD),
        (f"new_password={PASSWORD}", PASSWORD),
        (f"Authorization: Bearer {TOKEN}", TOKEN),
        (f"authorization: Basic {TOKEN}", TOKEN),
        (f"Cookie: __Host-session={SESSION}; csrf={TOKEN}", SESSION),
        (f"__Host-session={SESSION}", SESSION),
        (f'{{"login": "ivanov", "password": "{PASSWORD}"}}', PASSWORD),
        (f"{{'code': '{TOTP}'}}", TOTP),
        (f"code={TOTP}", TOTP),
        (f"redis://:{PASSWORD}@redis:6379/0", PASSWORD),
        (f"postgresql+asyncpg://estimator:{PASSWORD}@postgres/estimator", PASSWORD),
    ],
)
def test_values_in_text_are_masked(text: str, leak: str) -> None:
    masked = redact_text(text)
    assert leak not in masked
    assert REDACTED in masked


def test_harmless_text_kept() -> None:
    text = "status_code=200 error_code=NOT_FOUND login=ivanov path=/api/v1/projects"
    assert redact_text(text) == text


def test_nested_structures_and_header_pairs() -> None:
    value = {
        "request": {
            "headers": [
                (b"cookie", f"__Host-session={SESSION}".encode()),
                ("authorization", f"Bearer {TOKEN}"),
                (b"user-agent", b"Mozilla"),
            ],
            "body": {"login": "ivanov", "password": PASSWORD, "items": [{"code": TOTP}]},
            "url": f"https://app/reset?token={TOKEN}",
        },
        "deep": [[[[[[[[[[PASSWORD]]]]]]]]]],
    }
    dumped = json.dumps(redact(value), default=str)
    for leak in (SESSION, TOKEN, PASSWORD, TOTP):
        assert leak not in dumped
    assert "Mozilla" in dumped
    assert "ivanov" in dumped


def _records(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


@pytest.mark.spec("CL-11")
def test_login_and_reset_scenario_leaves_no_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    """Сценарий входа и сброса пароля: всё, что могло попасть в лог, попадает без секретов."""
    configure_logging("DEBUG")
    log = get_logger("auth")
    log.info("login_attempt", login="ivanov", password=PASSWORD, ip="10.0.0.1")
    log.info("totp_check", code=TOTP, step="totp")
    log.info("session_created", cookie=f"__Host-session={SESSION}", csrf_token=TOKEN)
    log.info("reset_requested", url=f"https://estimator/reset#token={TOKEN}", body=f"token={TOKEN}")
    log.debug("request", headers={"Cookie": f"__Host-session={SESSION}", "X-CSRF-Token": TOKEN})
    try:
        raise ValueError(f"bad credentials password={PASSWORD} token={TOKEN}")
    except ValueError:
        log.exception("login_failed")
    logging.getLogger("sqlalchemy").warning("params: {'password': '%s'}", PASSWORD)
    access = logging.getLogger("uvicorn.access")
    access.info(
        '%s - "%s %s HTTP/%s" %d',
        "10.0.0.1:5555",
        "POST",
        f"/api/v1/auth/password/reset?token={TOKEN}",
        "1.1",
        204,
    )
    out = _records(capsys)
    for leak in (PASSWORD, TOKEN, SESSION, TOTP):
        assert leak not in out, leak
    lines = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 8
    assert lines[0]["login"] == "ivanov"
    assert lines[-1]["event"].endswith('"POST /api/v1/auth/password/reset HTTP/1.1" 204')
    assert "Traceback" in lines[5]["exception"]


def test_access_filter_ignores_other_records() -> None:
    record = logging.LogRecord("uvicorn.access", 20, "", 0, "plain %s", ("x",), None)
    assert AccessLogQueryFilter().filter(record)
    assert record.args == ("x",)


def test_configure_logging_adds_access_filter_once() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, AccessLogQueryFilter) for f in access.filters) == 1
