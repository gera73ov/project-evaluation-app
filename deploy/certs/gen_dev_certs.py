"""Выпуск самоподписанных сертификатов для dev и test (INF-004).

Нужны, потому что ``__Host-``-cookie работают только по HTTPS, LDAPS и syslog по TLS
проверяют сертификат сервера (FR-AUTH-AD-02, SEC-AUD-05). Создаётся свой УЦ ``ca.crt`` и
сертификаты сервисов, подписанные им. Только для dev и test: на stage и prod сертификаты
выпускает служба эксплуатации.

Запуск: сервис ``certs`` в docker compose (образ api, где уже есть ``cryptography``)
или ``python gen_dev_certs.py <каталог>``. Существующие файлы не перезаписываются.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DAYS = 825
#: Сервис → (DNS-имена, IP, назначение). Имена — как в docker compose.
LEAVES: dict[str, tuple[list[str], list[str], list[x509.ObjectIdentifier]]] = {
    "nginx": (
        ["localhost", "estimator.localhost", "nginx"],
        ["127.0.0.1", "::1"],
        [ExtendedKeyUsageOID.SERVER_AUTH],
    ),
    # TLS до PostgreSQL (INF-014, SEC-CRYPT-05): приложение проверяет имя postgres (verify-full)
    "postgres": (["postgres", "localhost"], ["127.0.0.1"], [ExtendedKeyUsageOID.SERVER_AUTH]),
    "syslog": (["syslog", "localhost"], ["127.0.0.1"], [ExtendedKeyUsageOID.SERVER_AUTH]),
    "samba-ad": (
        ["samba-ad", "dc1.test.estimator.local", "test.estimator.local"],
        [],
        [ExtendedKeyUsageOID.SERVER_AUTH],
    ),
    "mailpit": (["mailpit", "localhost"], ["127.0.0.1"], [ExtendedKeyUsageOID.SERVER_AUTH]),
    # клиентский сертификат приложения для проверки mTLS с SIEM (SEC-AUD-05, GAP-09)
    "siem-client": (["estimator-api"], [], [ExtendedKeyUsageOID.CLIENT_AUTH]),
}


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Estimator dev"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # dev-ключи читают контейнеры с разными uid (nginx, samba, mailpit, syslog)
    path.chmod(0o644)


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o644)


def _load_or_create_ca(out: Path) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key_path, cert_path = out / "ca.key", out / "ca.crt"
    if key_path.exists() and cert_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise TypeError(f"{key_path}: ожидался ключ EC")
        return key, x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("Estimator dev CA"))
        .issuer_name(_name("Estimator dev CA"))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(key_path, key)
    _write_cert(cert_path, cert)
    return key, cert


def issue(out: Path) -> list[str]:
    """Выпустить недостающие сертификаты в ``out``; вернуть имена созданных."""
    out.mkdir(parents=True, exist_ok=True)
    ca_key, ca_cert = _load_or_create_ca(out)
    created = []
    now = dt.datetime.now(dt.UTC)
    for service, (dns, ips, usages) in LEAVES.items():
        crt, key_path = out / f"{service}.crt", out / f"{service}.key"
        if crt.exists() and key_path.exists():
            continue
        key = ec.generate_private_key(ec.SECP256R1())
        sans: list[x509.GeneralName] = [x509.DNSName(d) for d in dns]
        sans += [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
        cert = (
            x509.CertificateBuilder()
            .subject_name(_name(dns[0]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage(usages), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        _write_key(key_path, key)
        # цепочка: сертификат сервиса + УЦ (так их ждут nginx и samba)
        crt.write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
            + ca_cert.public_bytes(serialization.Encoding.PEM)
        )
        crt.chmod(0o644)
        created.append(service)
    return created


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/certs")
    made = issue(target)
    print(f"certs: выпущены {', '.join(made) or 'ничего (всё уже есть)'} в {target}")
