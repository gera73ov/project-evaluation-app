"""Сертификат Nginx стенда test выпускается на имя стенда (INF-011, deploy/envs/deploy.sh)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography import x509

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "deploy" / "certs"))

import gen_dev_certs  # noqa: E402

pytestmark = pytest.mark.spec("NFR-ENV-01")


def _dns(path: Path) -> list[str]:
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return san.get_values_for_type(x509.DNSName)


def test_nginx_cert_includes_stand_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERTS_NGINX_NAMES", "estimator-test.example.local localhost")
    gen_dev_certs.issue(tmp_path)
    names = _dns(tmp_path / "nginx.crt")
    assert names[:3] == ["localhost", "estimator.localhost", "nginx"]
    assert names.count("localhost") == 1
    assert "estimator-test.example.local" in names
    # остальные сервисы имя стенда не получают
    assert "estimator-test.example.local" not in _dns(tmp_path / "syslog.crt")


def test_nginx_cert_without_stand_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CERTS_NGINX_NAMES", raising=False)
    gen_dev_certs.issue(tmp_path)
    assert _dns(tmp_path / "nginx.crt") == ["localhost", "estimator.localhost", "nginx"]
