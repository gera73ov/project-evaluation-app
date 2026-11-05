"""SEC-003: ``rotate-key`` перешифровывает все зашифрованные столбцы (SEC-CRYPT-02, SPEC 18.4).

Таблицы — временные (``pg_temp`` первым в ``search_path``), с теми же именами и столбцами,
что в contracts/db/schema.md: тест не зависит от того, накатила ли схема DB-003.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.security.crypto import contexts
from estimator.security.crypto.aead import Cipher, encrypt_with, key_id, setting_blob
from estimator.security.crypto.keys import KeyRing, MasterKey
from estimator.security.crypto.rotation import rotate

pytestmark = [pytest.mark.spec("SEC-CRYPT-02"), pytest.mark.integration]

OLD = MasterKey("k1", b"\x01" * 32)
NEW = MasterKey("k2", b"\x02" * 32)


async def _tables(session: AsyncSession) -> None:
    for ddl in (
        "CREATE TEMP TABLE users (id uuid PRIMARY KEY, totp_secret_enc bytea)",
        "CREATE TEMP TABLE system_settings (key text PRIMARY KEY, value jsonb NOT NULL)",
        "CREATE TEMP TABLE customer_documents (id uuid PRIMARY KEY, key_enc bytea NOT NULL)",
    ):
        await session.execute(text(ddl))


async def _seed(session: AsyncSession) -> dict[str, object]:
    old = Cipher(KeyRing(OLD))
    u1, u2, d1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await session.execute(
        text("INSERT INTO users VALUES (:a, :sa), (:b, NULL)"),
        {"a": u1, "sa": old.encrypt(b"TOTPSECRET", contexts.totp_secret(u1)), "b": u2},
    )
    await session.execute(
        text(
            "INSERT INTO system_settings VALUES ('smtp.password', CAST(:s AS jsonb)), "
            "('app.timezone', CAST(:tz AS jsonb))"
        ),
        {
            "s": json.dumps(old.encrypt_setting("smtp.password", "smtp-pass")),
            "tz": json.dumps("Europe/Moscow"),
        },
    )
    await session.execute(
        text("INSERT INTO customer_documents VALUES (:d, :k)"),
        {"d": d1, "k": old.encrypt(b"\x07" * 32, contexts.document_key(d1))},
    )
    return {"user": u1, "doc": d1}


async def test_rotate_then_old_key_can_be_removed(db_session: AsyncSession) -> None:
    await _tables(db_session)
    ids = await _seed(db_session)
    conn = await db_session.connection()
    rotating = Cipher(KeyRing(NEW, (OLD,)))

    check = await rotate(conn, rotating, dry_run=True)
    assert check.remaining == 3
    assert check.errors == []

    report = await rotate(conn, rotating)
    assert report.errors == []
    assert {n: r.reencrypted for n, r in report.targets.items()} == {
        "users.totp_secret_enc": 1,
        "system_settings": 1,
        "customer_documents.key_enc": 1,
    }
    assert (await rotate(conn, rotating, dry_run=True)).remaining == 0

    only_new = Cipher(KeyRing(NEW))
    totp = (
        await db_session.execute(
            text("SELECT totp_secret_enc FROM users WHERE id = :i"), {"i": ids["user"]}
        )
    ).scalar_one()
    assert key_id(totp) == "k2"
    assert only_new.decrypt(totp, contexts.totp_secret(ids["user"])) == b"TOTPSECRET"
    smtp = (
        await db_session.execute(
            text("SELECT value FROM system_settings WHERE key = 'smtp.password'")
        )
    ).scalar_one()
    assert smtp["kid"] == "k2"
    assert key_id(setting_blob(smtp)) == "k2"
    assert only_new.decrypt_setting("smtp.password", smtp) == "smtp-pass"
    tz = (
        await db_session.execute(
            text("SELECT value FROM system_settings WHERE key = 'app.timezone'")
        )
    ).scalar_one()
    assert tz == "Europe/Moscow"
    key_enc = (
        await db_session.execute(text("SELECT key_enc FROM customer_documents"))
    ).scalar_one()
    assert only_new.decrypt(key_enc, contexts.document_key(ids["doc"])) == b"\x07" * 32


async def test_undecryptable_value_is_reported_not_touched(db_session: AsyncSession) -> None:
    await _tables(db_session)
    uid = uuid.uuid4()
    foreign = encrypt_with(MasterKey("k0", b"\x09" * 32), b"x", contexts.totp_secret(uid))
    swapped = encrypt_with(OLD, b"x", contexts.totp_secret(uuid.uuid4()))
    other = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users VALUES (:a, :x), (:b, :y)"),
        {"a": uid, "x": foreign, "b": other, "y": swapped},
    )
    conn = await db_session.connection()
    report = await rotate(conn, Cipher(KeyRing(NEW, (OLD,))))
    assert len(report.errors) == 2
    assert all("users.totp_secret_enc" in e for e in report.errors)
    assert "x" not in "".join(e.split(":", 1)[0] for e in report.errors)
    stored = (
        await db_session.execute(
            text("SELECT totp_secret_enc FROM users WHERE id = :a"), {"a": uid}
        )
    ).scalar_one()
    assert bytes(stored) == foreign


async def test_concurrent_change_is_not_overwritten(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Приложение записало новое значение между чтением и записью ротации — оно не затирается."""
    from estimator.security.crypto import rotation

    await _tables(db_session)
    ids = await _seed(db_session)
    # «прочитанное ротацией» состояние — снимок до записи приложения
    await db_session.execute(text("CREATE TEMP TABLE users_seen AS SELECT * FROM users"))
    rotating = Cipher(KeyRing(NEW, (OLD,)))
    fresh = rotating.encrypt(b"NEWSECRET", contexts.totp_secret(ids["user"]))
    await db_session.execute(
        text("UPDATE users SET totp_secret_enc = :v WHERE id = :i"), {"v": fresh, "i": ids["user"]}
    )
    target = rotation.TARGETS[0]
    seen = rotation.Target(
        name=target.name,
        select_sql=target.select_sql.replace("FROM users", "FROM users_seen"),
        update_sql=target.update_sql,
        context=target.context,
    )
    monkeypatch.setattr(rotation, "TARGETS", (seen,))
    report = await rotation.rotate(await db_session.connection(), rotating)
    rep = report.targets["users.totp_secret_enc"]
    assert (rep.changed_concurrently, rep.reencrypted, report.remaining) == (1, 0, 0)
    stored = (
        await db_session.execute(
            text("SELECT totp_secret_enc FROM users WHERE id = :i"), {"i": ids["user"]}
        )
    ).scalar_one()
    assert bytes(stored) == fresh
