"""Смоук-проверка стенда docker compose (INF-004, INF-005).

Запускается в образе api внутри сети стенда (``make smoke``) и проверяет, что сервисы не
просто живы, а отвечают по своим протоколам с проверкой сертификатов dev-УЦ:

* Nginx отдаёт SPA по HTTPS и проксирует /api; /health и /metrics наружу закрыты;
* api: /health/ready = ok (PostgreSQL и Redis);
* профиль test: syslog по TLS принимает событие RFC 5424; Mailpit принимает письмо по
  STARTTLS; Samba AD отвечает по LDAPS и StartTLS, вложенная группа даёт доступ, отключённая
  учётка помечена ACCOUNTDISABLE (тестовые данные deploy/samba-ad/seed.sh).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import smtplib
import socket
import ssl
import sys
import time
import uuid
from collections.abc import Callable
from email.message import EmailMessage

CA = os.environ.get("SMOKE_CA", "/certs/ca.crt")
BASE_DN = "DC=test,DC=estimator,DC=local"
ROOT = f"OU=Estimator,{BASE_DN}"
ACCOUNTDISABLE = 0x2
IN_CHAIN = "1.2.840.113556.1.4.1941"


def tls() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=CA)


def expect(condition: object, detail: object) -> None:
    if not condition:
        raise RuntimeError(str(detail))


def http_get(host: str, port: int, path: str) -> bytes:
    """HTTP внутри сети стенда (api и веб-интерфейс Mailpit наружу не публикуются по HTTPS)."""
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("GET", path)
    return conn.getresponse().read()


def https_get(path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPSConnection("nginx", 8443, context=tls(), timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.read()


def check_nginx() -> None:
    status, body = https_get("/")
    expect(status == 200 and b'<div id="root">' in body, status)
    expect(b"<script>" not in body, "inline-скрипт в index.html")
    for hidden in ("/health/ready", "/metrics"):
        expect(https_get(hidden)[0] == 404, hidden)
    status, _ = https_get("/api/v1/does-not-exist")
    expect(status == 404, status)


def check_api() -> None:
    body = json.loads(http_get("api", 8000, "/health/ready"))
    expect(body == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}, body)


def check_syslog() -> None:
    marker = f"smoke-{uuid.uuid4()}"
    msg = f'<110>1 2026-01-01T00:00:00Z smoke estimator - audit - {{"event":"{marker}"}}'
    raw = msg.encode()
    with (
        socket.create_connection(("syslog", 6514), timeout=10) as sock,
        tls().wrap_socket(sock, server_hostname="syslog") as conn,
    ):
        conn.sendall(f"{len(raw)} ".encode() + raw)
    print(f"  syslog: отправлено {marker}")


def check_mail() -> None:
    message = EmailMessage()
    message["From"] = "estimator@test.estimator.local"
    message["To"] = "expert.one@test.estimator.local"
    message["Subject"] = "Смоук-проверка"
    message.set_content("Проверка SMTP-ловушки")
    with smtplib.SMTP("mailpit", 1025, timeout=10) as smtp:
        smtp.starttls(context=tls())
        smtp.send_message(message)
    total = json.loads(http_get("mailpit", 8025, "/api/v1/messages"))["total"]
    expect(total >= 1, "письмо не дошло до Mailpit")


def check_ad() -> None:
    from ldap3 import NONE, SUBTREE, Connection, Server, Tls

    password = os.environ["SAMBA_TEST_PASSWORD"]
    tls_conf = Tls(ca_certs_file=CA, validate=ssl.CERT_REQUIRED)
    user = f"CN=svc-estimator,OU=Service,{ROOT}"
    for server in (
        Server("dc1.test.estimator.local", port=636, use_ssl=True, tls=tls_conf, get_info=NONE),
        Server("dc1.test.estimator.local", port=389, tls=tls_conf, get_info=NONE),
    ):
        conn = Connection(server, user=user, password=password, auto_bind=False)
        if not server.ssl:
            conn.open()
            expect(conn.start_tls(), "StartTLS не удался")
        expect(conn.bind(), conn.result)
        access = f"CN=est-access,OU=Groups,{ROOT}"
        conn.search(
            ROOT,
            f"(&(objectClass=user)(memberOf:{IN_CHAIN}:={access}))",
            SUBTREE,
            attributes=["sAMAccountName", "userAccountControl"],
        )
        members = {str(e.sAMAccountName): int(e.userAccountControl.value) for e in conn.entries}
        expect("expert.nested" in members, members)  # через est-presale-team → est-experts
        expect("no.access" not in members, members)
        expect(members["disabled.one"] & ACCOUNTDISABLE, members)
        conn.unbind()


def run(name: str, check: Callable[[], None], attempts: int = 10) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            check()
        except Exception as exc:  # noqa: BLE001 — сервисы поднимаются не сразу
            if attempt == attempts:
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
                return False
            time.sleep(3)
        else:
            print(f"ok   {name}")
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-profile", action="store_true", help="проверить эмуляторы")
    parser.add_argument("--skip", action="append", default=[], help="пропустить проверку")
    args = parser.parse_args()
    checks: list[tuple[str, Callable[[], None]]] = [("api", check_api), ("nginx", check_nginx)]
    if args.test_profile:
        checks += [("syslog", check_syslog), ("mailpit", check_mail), ("samba-ad", check_ad)]
    results = [run(name, check) for name, check in checks if name not in args.skip]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
