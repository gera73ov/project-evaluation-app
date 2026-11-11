"""INF-013: датчики эксплуатации для правил оповещений 18.4 (ops_metrics.refresh_once)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator import metrics, ops_metrics
from estimator.auth import ad_sync
from estimator.config import get_settings
from estimator.security.audit.verify import LAST_RESULT_KEY
from tests.integration.adm.test_system_health_api import marker, reachable  # noqa: F401
from tests.integration.core.conftest import World

pytestmark = [pytest.mark.integration, pytest.mark.spec("18.4")]

PEM_DAYS = 20


def _value(name: str, **labels: str) -> float | None:
    return metrics.REGISTRY.get_sample_value(name, labels)


def _pem(days: int) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .sign(key, hashes.SHA256())
    )  # fmt: skip
    return cert.public_bytes(serialization.Encoding.PEM)


def _files(marker: Path, backup_at: dt.datetime, cert: Path) -> None:  # noqa: F811
    marker.write_text(backup_at.isoformat() + "\n", encoding="utf-8")
    cert.write_bytes(_pem(PEM_DAYS))


async def test_refresh_sets_gauges(
    world: World,
    db_session: AsyncSession,
    redis_client: Redis,
    reachable: set[str],  # noqa: F811
    marker: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_at = dt.datetime(2026, 11, 11, 1, 5, tzinfo=dt.UTC)
    cert = tmp_path / "app.crt"
    _files(marker, backup_at, cert)
    monkeypatch.setenv("APP_TLS_CERT_PATH", str(cert))
    get_settings.cache_clear()
    await redis_client.set(LAST_RESULT_KEY, json.dumps({"ok": False, "first_broken_id": 7}))
    synced = dt.datetime(2026, 11, 11, 9, 45, tzinfo=dt.UTC)
    state = json.dumps({"at": synced.isoformat(), "ok": True})
    await redis_client.set(f"{ad_sync.STATE_KEY}:{ad_sync.SESSIONS}", state)

    async def version(*_: Any) -> str:
        return "ClamAV 1.5.4/27820/Mon Nov 10 07:39:51 2026\n"

    monkeypatch.setattr(ops_metrics, "clamav_version", version)
    await ops_metrics.refresh_once(db_session, redis_client, get_settings())

    assert _value("estimator_component_up", component="db") == 1
    assert _value("estimator_component_up", component="audit_chain") == 0
    assert _value("estimator_backup_last_success_timestamp_seconds") == backup_at.timestamp()
    assert _value("estimator_audit_chain_ok") == 0
    assert _value("estimator_ad_sync_last_success_timestamp_seconds", kind="sessions_15min") == (
        synced.timestamp()
    )
    assert _value("estimator_wal_archive_failing") == 0
    assert _value("estimator_clamav_up") == 1
    assert _value("estimator_clamav_db_timestamp_seconds") == (
        dt.datetime(2026, 11, 10, 7, 39, 51, tzinfo=dt.UTC).timestamp()
    )
    left = _value("estimator_cert_not_after_timestamp_seconds", cert="app")
    assert left is not None
    assert PEM_DAYS - 1 < (left - dt.datetime.now(dt.UTC).timestamp()) / 86400 <= PEM_DAYS

    async def down(*_: Any) -> str:
        raise OSError

    monkeypatch.setattr(ops_metrics, "clamav_version", down)
    await ops_metrics.refresh_once(db_session, redis_client, get_settings())
    assert _value("estimator_clamav_up") == 0
    get_settings.cache_clear()


def test_parsers() -> None:
    assert ops_metrics.cert_not_after(b"not a pem") is None
    assert ops_metrics.clamav_db_time("ClamAV 1.5.4") is None
    assert ops_metrics.clamav_db_time("ClamAV 1.5.4/1/garbage") is None


async def test_refresher_start_stop(redis_client: Redis) -> None:
    refresher = ops_metrics.Refresher(get_settings(), redis_client, lambda: None, interval=3600)  # type: ignore[arg-type,return-value]
    refresher.start()
    refresher.start()  # повторный старт не плодит задач
    await asyncio.sleep(0)
    await refresher.stop()
    await refresher.stop()
