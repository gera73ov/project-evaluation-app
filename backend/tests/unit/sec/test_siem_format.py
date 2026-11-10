"""SEC-012: формат syslog RFC 5424, кадр RFC 5425, настройки и метрики SIEM (SEC-AUD-05)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from estimator.security.siem import shipper

pytestmark = pytest.mark.spec("SEC-AUD-05")

BODY = {"time": "2026-11-10T09:00:00.000001Z", "type": "auth.logout", "result": "success",
        "user_id": None, "login": "ivanov", "ip": "10.0.0.1", "user_agent": None,
        "session_hash": None, "object_type": None, "object_id": None, "details": {},
        "prev_hash": "00" * 32}  # fmt: skip


@pytest.mark.parametrize(
    ("body", "severity"),
    [
        (BODY, 6),
        ({**BODY, "type": "auth.login.failed", "result": "failure"}, 4),
        ({**BODY, "type": "auth.password.reset_issued", "details": {"target_roles": ["admin"]}},
         1),
        ({**BODY, "type": "security.login_failures_burst", "result": "denied"}, 1),
        ({**BODY, "type": "neizvestnoe"}, 6),
    ],
)  # fmt: skip
def test_severity(body: dict[str, Any], severity: int) -> None:
    assert shipper.severity(body) == severity


def test_message_and_frame() -> None:
    message = shipper.format_message(42, BODY, "ab" * 32, "api-1")
    head, payload = message.split(" - audit - ", 1)
    assert head == "<110>1 2026-11-10T09:00:00.000001Z api-1 estimator"
    record = json.loads(payload)
    assert (record["id"], record["category"], record["hash"]) == (42, "auth", "ab" * 32)
    assert "\n" not in message
    framed = shipper.frame("<110>1 Ёж")
    assert framed == b"11 <110>1 \xd0\x81\xd0\xb6"  # длина в байтах UTF-8, не в символах
    assert shipper.format_message(1, {"type": "x"}, "h", "").startswith("<110>1 - - estimator")


def test_config_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert shipper.SiemConfig.from_settings(None) == shipper.SiemConfig()
    plain = shipper.SiemConfig.from_settings(
        {"enabled": True, "host": "siem", "port": None}, "фиктивный ключ в открытом виде"
    )
    assert (plain.enabled, plain.port, plain.client_key_pem) == (
        True, 6514, "фиктивный ключ в открытом виде")  # fmt: skip

    class FakeCipher:
        def decrypt_setting(self, key: str, value: dict[str, str]) -> str:
            return f"{key}:{value['enc']}"

    import estimator.security.crypto as crypto

    monkeypatch.setattr(crypto, "get_cipher", lambda: FakeCipher())
    encrypted = shipper.SiemConfig.from_settings({}, {"enc": "eA", "kid": "k1"})
    assert encrypted.client_key_pem == "siem.client_key:eA"
    assert "eA" not in repr(encrypted)


def test_send_requires_host_and_ca() -> None:
    with pytest.raises(shipper.SiemError, match="адрес"):
        shipper.send_tls(shipper.SiemConfig(enabled=True), [b"x"])
    with pytest.raises(shipper.SiemError, match="УЦ"):
        shipper.send_tls(shipper.SiemConfig(enabled=True, host="siem"), [b"x"])


def test_queue_collector() -> None:
    def metrics(reader: Any) -> dict[str, float]:
        return {m.name: m.samples[0].value for m in shipper.QueueCollector(reader).collect()}

    state = {"enabled": True, "ok": False, "backlog": 12, "overflow_at": "2026-11-10"}
    assert metrics(lambda: state) == {"estimator_siem_queue_length": 12, "estimator_siem_up": 0,
                                      "estimator_siem_overflow": 1}  # fmt: skip
    assert metrics(lambda: {"enabled": False}) == {}
    assert metrics(lambda: None) == {}

    def broken() -> None:
        raise ConnectionError("redis down")

    assert metrics(broken) == {}


def test_state_reader_without_redis() -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011 — любой сбой подключения
        shipper.read_state_sync("redis://127.0.0.1:1/0")
