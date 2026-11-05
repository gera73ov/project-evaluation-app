"""INF-002: JSON-логи и request_id (NFR-MNT-04, SEC-AUTH-04)."""

from __future__ import annotations

import json
import logging

import pytest

from estimator.logging import (
    REDACTED,
    RequestIdMiddleware,
    bind_context,
    configure_logging,
    get_logger,
    new_request_id,
)

pytestmark = pytest.mark.spec("NFR-MNT-04")


def _last_json(capsys: pytest.CaptureFixture[str]) -> dict:
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_one_json_line_with_base_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("t").info("project_opened", extra_field=1)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    rec = json.loads(out[0])
    for key in ("time", "level", "request_id", "user_id", "project_id", "event"):
        assert key in rec
    assert rec["event"] == "project_opened"
    assert rec["level"] == "info"
    assert rec["time"].endswith("Z")


def test_context_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    bind_context(user_id="u1", project_id="p1")
    get_logger().info("x")
    rec = _last_json(capsys)
    assert rec["user_id"] == "u1"
    assert rec["project_id"] == "p1"


@pytest.mark.spec("SEC-AUTH-04")
def test_secrets_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger().info(
        "login",
        password="p@ss",
        details={"totp_code": "123456", "nested": [{"api_key": "k"}], "ok": 1},
    )
    rec = _last_json(capsys)
    assert rec["password"] == REDACTED
    assert rec["details"]["totp_code"] == REDACTED
    assert rec["details"]["nested"][0]["api_key"] == REDACTED
    assert rec["details"]["ok"] == 1


def test_stdlib_logs_are_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("uvicorn.error").warning("library message")
    rec = _last_json(capsys)
    assert rec["event"] == "library message"
    assert rec["level"] == "warning"


def test_level_filter(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    get_logger().info("hidden")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [("abcdef12-3456", True), ("bad id with spaces", False), ("x" * 65, False), (None, False)],
)
def test_new_request_id(incoming: str | None, kept: bool) -> None:
    rid = new_request_id(incoming)
    assert (rid == incoming) is kept
    assert len(rid) >= 8


async def test_middleware_passes_lifespan() -> None:
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])

    await RequestIdMiddleware(app)({"type": "lifespan"}, None, None)
    assert called == ["lifespan"]


async def test_middleware_websocket_gets_id() -> None:
    seen = {}

    async def app(scope, receive, send):
        seen.update(scope["state"])

    await RequestIdMiddleware(app)(
        {"type": "websocket", "headers": [(b"x-request-id", b"ws-req-000001")]}, None, None
    )
    assert seen["request_id"] == "ws-req-000001"
