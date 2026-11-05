"""Создать .env из .env.example со случайными паролями (INF-004, `make env`).

Существующий .env не трогается. Только стандартная библиотека Python 3.
"""

from __future__ import annotations

import base64
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def _encryption_key() -> str:
    """Мастер-ключ SEC-003 в формате ``<id>:<base64url 32 байта>``."""
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    return f"{datetime.now(UTC):k%Y%m%d}:{raw}"


RANDOM = {
    "ENCRYPTION_KEY": _encryption_key,
    "POSTGRES_PASSWORD": lambda: secrets.token_hex(24),
    "REDIS_PASSWORD": lambda: secrets.token_hex(24),
    # политика паролей AD: заглавные, строчные, цифры
    "SAMBA_ADMIN_PASSWORD": lambda: f"Est-{secrets.token_hex(12)}-9",
    "SAMBA_TEST_PASSWORD": lambda: f"Est-{secrets.token_hex(12)}-9",
}


def render(example: str) -> str:
    lines = []
    for line in example.splitlines():
        name = line.split("=", 1)[0]
        lines.append(f"{name}={RANDOM[name]()}" if name in RANDOM else line)
    return "\n".join(lines) + "\n"


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env уже есть, не меняю")
        return 0
    target.write_text(render((ROOT / ".env.example").read_text(encoding="utf-8")), encoding="utf-8")
    target.chmod(0o600)
    print("создан .env со случайными паролями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
