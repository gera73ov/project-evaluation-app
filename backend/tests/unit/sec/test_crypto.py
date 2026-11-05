"""SEC-003: AES-256-GCM с идентификатором ключа, envelope-шифрование, ключи из окружения."""

from __future__ import annotations

import io
import os

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.config import Settings
from estimator.security.crypto import contexts
from estimator.security.crypto.aead import Cipher, DecryptionError, encrypt_with, key_id
from estimator.security.crypto.envelope import (
    CHUNK,
    decrypt_stream,
    encrypt_stream,
    new_data_key,
    unwrap_data_key,
    wrap_data_key,
)
from estimator.security.crypto.keys import (
    KeyConfigError,
    KeyRing,
    MasterKey,
    format_key,
    generate_key,
    keyring_from_settings,
    parse_key,
)

pytestmark = [pytest.mark.spec("SEC-CRYPT-02"), pytest.mark.spec("SEC-CRYPT-03")]

K1 = MasterKey("k1", b"\x01" * 32)
K2 = MasterKey("k2", b"\x02" * 32)
CTX = contexts.totp_secret("0192f1c4-7a1e-7c3b-9f00-1a2b3c4d5e6f")


def test_roundtrip_and_key_id_inside_value() -> None:
    cipher = Cipher(KeyRing(K1))
    blob = cipher.encrypt_text("JBSWY3DPEHPK3PXP", CTX)
    assert key_id(blob) == "k1"
    assert b"JBSWY3DPEHPK3PXP" not in blob
    assert cipher.decrypt_text(blob, CTX) == "JBSWY3DPEHPK3PXP"
    assert cipher.encrypt_text("x", CTX) != cipher.encrypt_text("x", CTX)  # случайный nonce


@pytest.mark.parametrize("position", [0, 1, 3, 10, -1, -17])
def test_tampering_is_detected(position: int) -> None:
    cipher = Cipher(KeyRing(K1))
    blob = bytearray(cipher.encrypt_text("secret", CTX))
    blob[position] ^= 0x01
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(blob), CTX)


def test_value_bound_to_its_place() -> None:
    """Шифротекст из строки одного пользователя не читается в строке другого."""
    cipher = Cipher(KeyRing(K1))
    blob = cipher.encrypt_text("secret", contexts.totp_secret("a"))
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, contexts.totp_secret("b"))
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, contexts.document_key("a"))


@pytest.mark.parametrize("blob", [b"", b"\x02\x01k", b"\x01\x00" + b"\x00" * 40, b"\x01\x05k1"])
def test_malformed_values(blob: bytes) -> None:
    with pytest.raises(DecryptionError):
        Cipher(KeyRing(K1)).decrypt(blob, CTX)


def test_non_ascii_kid_in_blob() -> None:
    blob = b"\x01\x02\xff\xfe" + b"\x00" * 40
    with pytest.raises(DecryptionError):
        Cipher(KeyRing(K1)).decrypt(blob, CTX)


def test_rotation_reads_old_writes_new() -> None:
    old_blob = encrypt_with(K1, b"secret", CTX)
    cipher = Cipher(KeyRing(K2, (K1,)))
    assert cipher.needs_rotation(old_blob)
    new_blob = cipher.reencrypt(old_blob, CTX)
    assert key_id(new_blob) == "k2"
    assert not cipher.needs_rotation(new_blob)
    # старый ключ убран — новое значение читается, старое — нет
    only_new = Cipher(KeyRing(K2))
    assert only_new.decrypt(new_blob, CTX) == b"secret"
    with pytest.raises(DecryptionError, match="неизвестным ключом k1"):
        only_new.decrypt(old_blob, CTX)


def test_settings_secret_format() -> None:
    cipher = Cipher(KeyRing(K1))
    stored = cipher.encrypt_setting("smtp.password", "p@ss")
    assert set(stored) == {"enc", "kid"}
    assert stored["kid"] == "k1"
    assert "p@ss" not in str(stored)
    assert cipher.decrypt_setting("smtp.password", stored) == "p@ss"
    with pytest.raises(DecryptionError):
        cipher.decrypt_setting("auth.ad.bind_password", stored)
    with pytest.raises(DecryptionError):
        cipher.decrypt_setting("smtp.password", {"enc": "!!!", "kid": "k1"})
    with pytest.raises(DecryptionError):
        cipher.decrypt_setting("smtp.password", {**stored, "kid": "k2"})
    with pytest.raises(DecryptionError):
        cipher.decrypt_setting("smtp.password", {"value": "plain"})


# --- ключи ---


def test_key_format_roundtrip() -> None:
    key = generate_key("k20261105")
    assert parse_key(format_key(key)) == key
    assert "key=" not in repr(key)
    assert key.key.hex() not in repr(key)


@pytest.mark.parametrize(
    "text",
    ["", "k1", ":AAAA", "k1:", "k1:%%%", "k1:" + "A" * 10, "bad id:" + "A" * 43, "k" * 33 + ":A"],
)
def test_bad_keys(text: str) -> None:
    with pytest.raises(KeyConfigError):
        parse_key(text)


def test_keyring_from_settings() -> None:
    new, old = generate_key("k2"), generate_key("k1")
    settings = Settings(
        encryption_key=SecretStr(format_key(new)),
        encryption_keys_old=SecretStr(f" {format_key(old)} ,"),
    )
    ring = keyring_from_settings(settings)
    assert ring.current == new
    assert ring.kids == ("k2", "k1")
    assert ring.get("k1") == old
    assert ring.get("k3") is None


def test_keyring_requires_key_and_unique_ids() -> None:
    with pytest.raises(KeyConfigError, match="ENCRYPTION_KEY"):
        keyring_from_settings(Settings())
    key = format_key(generate_key("k1"))
    with pytest.raises(KeyConfigError, match="повторяются"):
        keyring_from_settings(
            Settings(encryption_key=SecretStr(key), encryption_keys_old=SecretStr(key))
        )


def test_key_not_in_settings_repr() -> None:
    key = format_key(generate_key("k1"))
    settings = Settings(encryption_key=SecretStr(key))
    assert key.split(":")[1] not in repr(settings)


def test_get_cipher_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from estimator.security.crypto import get_cipher

    monkeypatch.setenv("ENCRYPTION_KEY", format_key(K1))
    get_cipher.cache_clear()
    try:
        assert get_cipher().current_kid == "k1"
    finally:
        get_cipher.cache_clear()


def test_generate_key_command() -> None:
    cli.load_commands()
    result = CliRunner().invoke(cli.app, ["generate-key", "--id", "k20270101"])
    assert result.exit_code == 0, result.output
    keys = [ln for ln in result.stdout.splitlines() if ln.startswith("k20270101:")]
    assert len(keys) == 1
    assert parse_key(keys[0]).kid == "k20270101"
    bad = CliRunner().invoke(cli.app, ["generate-key", "--id", "плохой"])
    assert bad.exit_code == 2


def test_rotate_key_without_key_exits_2() -> None:
    cli.load_commands()
    result = CliRunner().invoke(cli.app, ["rotate-key", "--check"])
    assert result.exit_code == 2
    assert "ENCRYPTION_KEY" in result.output


# --- envelope (SEC-CRYPT-06) ---

DOC = contexts.document_key("0192f1c4-7a1e-7c3b-9f00-000000000001")


@pytest.mark.spec("SEC-CRYPT-06")
@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 5])
def test_file_roundtrip(size: int) -> None:
    data = os.urandom(size)
    key = new_data_key()
    enc = io.BytesIO()
    assert encrypt_stream(io.BytesIO(data), enc, key, DOC) == size
    if size >= 16:  # короткий открытый текст может случайно встретиться в шифротексте
        assert data[:64] not in enc.getvalue()
    out = io.BytesIO()
    assert decrypt_stream(io.BytesIO(enc.getvalue()), out, key, DOC) == size
    assert out.getvalue() == data


def _encrypted(size: int) -> tuple[bytes, bytes]:
    key = new_data_key()
    enc = io.BytesIO()
    encrypt_stream(io.BytesIO(os.urandom(size)), enc, key, DOC)
    return key, enc.getvalue()


@pytest.mark.spec("SEC-CRYPT-06")
def test_file_truncation_and_reordering_detected() -> None:
    key, blob = _encrypted(3 * CHUNK)
    block = CHUNK + 16
    header, body = blob[:12], blob[12:]
    blocks = [body[i : i + block] for i in range(0, len(body), block)]
    variants = {
        "обрезан последний блок": header + b"".join(blocks[:-1]),
        "обрезан хвост": blob[:-1],
        "переставлены блоки": header + blocks[1] + blocks[0] + blocks[2],
        "заменён байт": blob[:100] + bytes([blob[100] ^ 1]) + blob[101:],
        "другой заголовок": b"XXXX" + blob[4:],
        "пусто": b"",
    }
    for name, variant in variants.items():
        with pytest.raises(DecryptionError):
            decrypt_stream(io.BytesIO(variant), io.BytesIO(), key, DOC)
        assert name


@pytest.mark.spec("SEC-CRYPT-06")
def test_file_bound_to_document_and_key() -> None:
    key, blob = _encrypted(10)
    with pytest.raises(DecryptionError):
        decrypt_stream(io.BytesIO(blob), io.BytesIO(), key, contexts.document_key("другой"))
    with pytest.raises(DecryptionError):
        decrypt_stream(io.BytesIO(blob), io.BytesIO(), new_data_key(), DOC)


@pytest.mark.spec("SEC-CRYPT-06")
def test_data_key_wrapping() -> None:
    cipher = Cipher(KeyRing(K1))
    dek = new_data_key()
    wrapped = wrap_data_key(cipher, dek, DOC)
    assert dek not in wrapped
    assert unwrap_data_key(cipher, wrapped, DOC) == dek
    with pytest.raises(ValueError, match="32 байта"):
        wrap_data_key(cipher, b"short", DOC)
    with pytest.raises(DecryptionError):
        unwrap_data_key(cipher, cipher.encrypt(b"short", DOC), DOC)
