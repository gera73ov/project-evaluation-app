"""NTF-002: почтовый клиент, шаблоны писем, получатели и задача отправки."""

from __future__ import annotations

import re
import smtplib
from pathlib import Path
from typing import Any, ClassVar

import pytest
from jinja2 import meta, nodes

from estimator.notifications import tasks
from estimator.notifications.mail import (
    EMAIL_FIELDS,
    Recipient,
    SmtpConfig,
    SmtpNotConfiguredError,
    build_message,
    deliverable,
    render_email,
    send_message,
    send_test_email,
)
from estimator.notifications.mail import render as render_mod
from estimator.notifications.mail import sender as sender_mod
from estimator.notifications.mail.render import PROJECT_ITEM_FIELDS, plural
from estimator.security.crypto.aead import Cipher
from estimator.security.crypto.keys import KeyRing, MasterKey, format_key
from tests.support.smtp_sink import SmtpSink
from tests.unit._contracts import load_yaml

pytestmark = [pytest.mark.spec("FR-NOTIF-02"), pytest.mark.spec("FR-NOTIF-03")]

N = load_yaml("notifications.yaml")
TEMPLATES = Path(render_mod.__file__).resolve().parents[1] / "templates"
LINK = "https://estimator.example/projects/1"

SAMPLES: dict[str, dict[str, Any]] = {
    "digest": {
        "projects": [
            {"project_name": "Портал дилеров", "counters": {"question_to_me": 3}, "link": LINK},
            {"project_name": "CRM", "counters": {"branch_back_to_draft": 1}, "link": LINK},
        ],
        "total": 4,
    },
    "questions_batch": {
        "projects": [{"project_name": "Портал дилеров", "questions": 0, "answers": 1, "link": LINK}]
    },
    "assigned_to_project": {"project_name": "Портал дилеров", "link": LINK},
    "password_setup": {"link": LINK, "expires_hours": 72},
    "password_reset": {"link": LINK, "expires_minutes": 60},
    "new_device_login": {
        "browser": "Firefox", "subnet": "10.1.2.0/24", "time": "05.11.2026 15:00", "link": LINK,
    },
    "remind_not_started": {"project_name": "Портал дилеров", "deadline": "10.11.2026",
                           "link": LINK},
    "security_alert": {"alert": "login_failures_burst", "time": "05.11.2026 15:00",
                       "actor_login": None, "ip": "10.0.0.5", "link": LINK},
    "smtp_test": {"link": LINK},
}  # fmt: skip


def _config(port: int, **kw: Any) -> SmtpConfig:
    values: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": port,
        "security": "none",
        "from_address": "estimator@example.org",
        "from_name": "Оценка проектов",
        "timeout_seconds": 5,
    }
    values.update(kw)
    return SmtpConfig(**values)


# --- контракт и шаблоны ---


def test_email_fields_match_contract() -> None:
    contract = {k: frozenset(v["email_fields"]) for k, v in N["emails"].items()}
    assert contract == EMAIL_FIELDS


def _template_variables(path: Path) -> tuple[set[str], set[str]]:
    env = render_mod._env
    ast = env.parse(path.read_text(encoding="utf-8"))
    stored = {n.name for n in ast.find_all(nodes.Name) if n.ctx == "store"}
    top = meta.find_undeclared_variables(ast) - stored
    attrs = {
        node.attr
        for node in ast.find_all(nodes.Getattr)
        if not (isinstance(node.node, nodes.Name) and node.node.name == "loop")
    }
    return top, attrs


FORBIDDEN = re.compile(
    r"(rate|cost|money|amount|price|currency|vat|title|node|text|body|message|comment|estimate|"
    r"hours|^o$|^r$|^p$|note)",
    re.I,
)
GLOBALS = {"kind_label", "alert_label", "plural", "subject", "label"}


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_templates_use_only_contract_fields(kind: str) -> None:
    """Линтер шаблонов: только поля контракта, нет денег, названий узлов и текстов (Q-37)."""
    allowed = render_mod.ALL_FIELDS[kind]
    for suffix in ("txt", "html"):
        top, attrs = _template_variables(TEMPLATES / f"{kind}.{suffix}")
        assert top - GLOBALS <= allowed, (kind, suffix, top - GLOBALS - allowed)
        assert attrs <= PROJECT_ITEM_FIELDS, (kind, suffix, attrs - PROJECT_ITEM_FIELDS)
        for name in (top - GLOBALS) | attrs:
            if name in allowed or name == "project_name":
                continue  # поле контракта — проверено выше
            assert not FORBIDDEN.search(name), (kind, name)


def test_every_template_file_is_known() -> None:
    names = {p.stem for p in TEMPLATES.glob("*.txt")}
    assert names == set(SAMPLES)
    assert {p.stem for p in TEMPLATES.glob("*.html") if not p.stem.startswith("_")} == names


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_render_all(kind: str) -> None:
    rendered = render_email(kind, SAMPLES[kind])
    assert rendered.subject
    assert "\n" not in rendered.subject
    assert rendered.text.strip()
    assert "<html" in rendered.html
    assert LINK in rendered.text
    assert LINK in rendered.html


def test_examples_from_spec() -> None:
    assert render_email("questions_batch", SAMPLES["questions_batch"]).subject == (
        "«Портал дилеров»: 1 ответ на ваш вопрос"
    )
    digest = render_email("digest", SAMPLES["digest"])
    assert digest.subject == "Сводка: 4 новых события в 2 проектах"
    assert "вопросы вам — 3" in digest.text


def test_html_is_escaped_text_is_not() -> None:
    fields = {"project_name": "<script>alert(1)</script> & Co", "link": LINK}
    rendered = render_email("assigned_to_project", fields)
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "<script>alert(1)</script> & Co" in rendered.text


def test_extra_and_missing_fields_rejected() -> None:
    with pytest.raises(ValueError, match="не разрешены"):
        render_email("assigned_to_project", {"project_name": "X", "link": LINK, "rate": 3000})
    with pytest.raises(ValueError, match="в projects"):
        render_email(
            "questions_batch",
            {"projects": [{"project_name": "X", "questions": 1, "answers": 0, "link": LINK,
                           "node_title": "Секрет"}]},
        )  # fmt: skip
    with pytest.raises(ValueError, match="неизвестный"):
        render_email("nope", {})
    with pytest.raises(ValueError, match="link"):
        render_email("password_reset", {"expires_minutes": 60})


@pytest.mark.parametrize(
    ("n", "word"),
    [(1, "вопрос"), (2, "вопроса"), (4, "вопроса"), (5, "вопросов"), (11, "вопросов"),
     (12, "вопросов"), (21, "вопрос"), (22, "вопроса"), (111, "вопросов"), (0, "вопросов")],
)  # fmt: skip
def test_plural(n: int, word: str) -> None:
    assert plural(n, "вопрос", "вопроса", "вопросов") == word


# --- получатели ---


def test_recipients_rules() -> None:
    people = [
        Recipient("a@x.ru", "active"),
        Recipient(None, "active"),
        Recipient("", "active"),
        Recipient("b@x.ru", "blocked"),
        Recipient("c@x.ru", "pending_password"),
        Recipient("d@x.ru", "anonymized"),
        Recipient("a@x.ru", "active"),
    ]
    assert deliverable("digest", people) == ["a@x.ru"]
    assert deliverable("password_setup", people) == ["a@x.ru", "c@x.ru"]


# --- отправка ---


def test_message_headers() -> None:
    config = _config(25)
    msg = build_message(config, "ivanov@example.org", render_email("smtp_test", {"link": LINK}))
    assert msg["To"] == "ivanov@example.org"
    assert "estimator@example.org" in msg["From"]
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg["Message-ID"].endswith("@example.org>")
    assert msg.is_multipart()


def test_send_to_smtp_sink_with_login() -> None:
    with SmtpSink(password="smtp-pass") as sink:
        config = _config(sink.port, username="robot", password="smtp-pass")
        send_test_email(config, "admin@example.org", LINK)
    assert len(sink.messages) == 1
    msg = sink.messages[0]
    assert msg["Subject"] == "Тестовое письмо «Оценки проектов»"
    assert sink.envelopes[0][1] == ["admin@example.org"]
    assert sink.logins == [("robot", "smtp-pass")]
    assert LINK in msg.get_body(("plain",)).get_content()  # type: ignore[union-attr]


def test_not_configured() -> None:
    with pytest.raises(SmtpNotConfiguredError):
        send_test_email(SmtpConfig(host=None), "a@x.ru", LINK)
    with pytest.raises(SmtpNotConfiguredError):
        send_test_email(SmtpConfig(host="smtp", from_address=None), "a@x.ru", LINK)


class _FakeSMTP:
    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float, context: Any = None) -> None:
        self.calls: list[str] = [f"connect {host}:{port}"]
        self.context = context
        _FakeSMTP.instances.append(self)

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")
        self.context = context

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}")

    def send_message(self, msg: Any) -> None:
        self.calls.append("send")

    def quit(self) -> None:
        raise smtplib.SMTPServerDisconnected("gone")

    def close(self) -> None:
        self.calls.append("close")


@pytest.mark.spec("SEC-CRYPT-03")
@pytest.mark.parametrize(
    ("security", "expected"),
    [("starttls", ["connect smtp:587", "starttls", "send", "close"]),
     ("tls", ["connect smtp:587", "send", "close"])],
)  # fmt: skip
def test_tls_modes_verify_certificates(
    monkeypatch: pytest.MonkeyPatch, security: str, expected: list[str]
) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(sender_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP_SSL", _FakeSMTP)
    config = SmtpConfig(host="smtp", port=587, security=security, from_address="e@x.ru")
    send_message(config, build_message(config, "a@x.ru", render_email("smtp_test", {"link": LINK})))
    client = _FakeSMTP.instances[0]
    assert client.calls == expected
    assert client.context.verify_mode.name == "CERT_REQUIRED"
    assert client.context.check_hostname


# --- параметры SMTP из настроек ---

KEY = MasterKey("k1", b"\x05" * 32)


def test_config_from_settings_decrypts_password() -> None:
    cipher = Cipher(KeyRing(KEY))
    server = {"host": "smtp.corp", "port": 465, "security": "tls", "username": "robot",
              "from_address": "e@corp.ru", "from_name": "Оценка", "timeout_seconds": 7}  # fmt: skip
    config = SmtpConfig.from_settings(server, cipher.encrypt_setting("smtp.password", "pw"), cipher)
    assert config.password == "pw"
    assert config.port == 465
    assert "pw" not in repr(config)
    assert SmtpConfig.from_settings(None, None) == SmtpConfig(host=None)
    assert SmtpConfig.from_settings(server, "plain").password == "plain"
    with pytest.raises(ValueError, match="шифратор"):
        SmtpConfig.from_settings(server, cipher.encrypt_setting("smtp.password", "pw"))


@pytest.mark.integration
async def test_load_smtp_settings(db_session: Any) -> None:
    import json

    from sqlalchemy import text

    from estimator.notifications.mail.config import load_smtp_settings

    await db_session.execute(
        text("CREATE TEMP TABLE system_settings (key text PRIMARY KEY, value jsonb NOT NULL)")
    )
    await db_session.execute(
        text("INSERT INTO system_settings VALUES ('smtp.server', CAST(:v AS jsonb))"),
        {"v": json.dumps({"host": "smtp.corp"})},
    )
    server, password = await load_smtp_settings(await db_session.connection())
    assert server == {"host": "smtp.corp"}
    assert password is None


# --- задача Celery ---


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (smtplib.SMTPServerDisconnected("x"), True),
        (TimeoutError(), True),
        (ConnectionRefusedError(), True),
        (smtplib.SMTPResponseException(451, b"later"), True),
        (smtplib.SMTPResponseException(550, b"no"), False),
        (smtplib.SMTPAuthenticationError(535, b"bad"), False),
        (smtplib.SMTPRecipientsRefused({"a@x": (450, b"later")}), True),
        (smtplib.SMTPRecipientsRefused({"a@x": (550, b"no")}), False),
        (ValueError("bug"), False),
    ],
)
def test_transient_errors(exc: BaseException, transient: bool) -> None:
    assert tasks.is_transient(exc) is transient


def test_retry_delay_grows_to_30_minutes() -> None:
    assert [tasks.retry_delay(n) for n in range(8)] == [30, 60, 120, 240, 480, 960, 1800, 1800]


def _override(port: int, cipher: Cipher | None = None) -> dict[str, Any]:
    server = {"host": "127.0.0.1", "port": port, "security": "none", "username": None,
              "from_address": "e@x.ru", "from_name": "Оценка", "timeout_seconds": 5}  # fmt: skip
    return {"server": server, "password": None}


def test_task_sends_through_explicit_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отправка через явно указанный (старый) сервер — для оповещения о смене SMTP (SEC-011)."""
    cipher = Cipher(KeyRing(KEY))
    monkeypatch.setenv("ENCRYPTION_KEY", format_key(KEY))
    from estimator.security.crypto import get_cipher

    get_cipher.cache_clear()
    try:
        with SmtpSink(password="old-pass") as sink:
            override = _override(sink.port)
            override["server"]["username"] = "robot"
            override["password"] = cipher.encrypt_setting("smtp.password", "old-pass")
            result = tasks.send_email.apply(
                args=("security_alert", "ib@corp.ru", SAMPLES["security_alert"], override)
            )
        assert result.get() == "sent"
        assert sink.logins == [("robot", "old-pass")]
        assert sink.messages[0]["Subject"].startswith("Оповещение ИБ")
    finally:
        get_cipher.cache_clear()


def test_task_retries_on_temporary_failure() -> None:
    with SmtpSink() as sink:
        sink.fail_codes = [451]
        result = tasks.send_email.apply(
            args=("smtp_test", "a@x.ru", {"link": LINK}, _override(sink.port))
        )
    # eager-режим: повтор выполняется сразу, письмо уходит со второй попытки
    assert result.get() == "sent"
    assert len(sink.messages) == 1


def test_task_does_not_retry_permanent_failure() -> None:
    with SmtpSink() as sink:
        sink.fail_codes = [550]
        result = tasks.send_email.apply(
            args=("smtp_test", "a@x.ru", {"link": LINK}, _override(sink.port))
        )
    assert isinstance(result.result, smtplib.SMTPResponseException)
    assert sink.messages == []


def test_task_skips_when_smtp_not_configured() -> None:
    override = {"server": {"host": None}, "password": None}
    result = tasks.send_email.apply(args=("smtp_test", "a@x.ru", {"link": LINK}, override))
    assert result.get() == "skipped"


def test_enqueue_filters_recipients(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(tasks.send_email, "delay", lambda *args: sent.append(args))
    people = [Recipient("a@x.ru", "active"), Recipient(None, "active"),
              Recipient("b@x.ru", "blocked")]  # fmt: skip
    count = tasks.enqueue_email("assigned_to_project", people, SAMPLES["assigned_to_project"])
    assert count == 1
    assert sent == [("assigned_to_project", "a@x.ru", SAMPLES["assigned_to_project"], None)]
    with pytest.raises(ValueError, match="не разрешены"):
        tasks.enqueue_email("assigned_to_project", people, {"project_name": "X", "link": LINK,
                                                           "deadline": "1"})  # fmt: skip
