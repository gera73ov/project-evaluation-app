"""SEC-009: access-лог Nginx не содержит строки запроса, cookie и Authorization (SEC-AUTH-04)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[4] / "deploy" / "nginx"
FORBIDDEN = re.compile(
    r"\$(request|request_uri|args|arg_\w+|query_string|is_args|request_body|http_cookie|"
    r"cookie_\w+|http_authorization|http_x_csrf_token|sent_http_set_cookie|"
    r"upstream_http_set_cookie|remote_user)\b"
)

pytestmark = pytest.mark.spec("SEC-AUTH-04")


def _configs() -> list[Path]:
    return sorted(HERE.rglob("*.conf"))


def test_log_format_has_no_secret_variables() -> None:
    text = (HERE / "log_format.conf").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "log_format json" in body
    assert "$uri" in body
    assert FORBIDDEN.findall(body) == []


def test_no_other_log_formats_or_secret_logging() -> None:
    """Других форматов нет, и ни один конфиг не пишет секретные переменные в лог."""
    for path in _configs():
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if path.name != "log_format.conf":
                assert not re.match(r"\s*log_format\s", code), path
            if "access_log" in code:
                assert re.search(r"access_log\s+(off|\S+\s+json)\s*;", code), (path, line)


def test_log_format_included_before_use() -> None:
    main = (HERE / "nginx.conf").read_text(encoding="utf-8")
    assert main.index("include /etc/nginx/log_format.conf;") < main.index("access_log")
    dockerfile = (HERE.parent / "docker" / "nginx.Dockerfile").read_text(encoding="utf-8")
    assert "deploy/nginx/log_format.conf /etc/nginx/log_format.conf" in dockerfile
